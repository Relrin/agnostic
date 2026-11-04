"""Org settings > Authentication through the HTTP API: providers managed in the app (OIDC and SAML), SAML sign-in
end to end, enforced SSO with a break-glass Owner, two-step sign-in (TOTP, recovery codes, security keys) and
step-up re-authentication."""

import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_identity.application.ports import SessionStore
from agnostic_identity.domain import totp
from agnostic_identity.facade import SESSION_COOKIE
from agnostic_identity.infrastructure.tables import ExternalIdentityRow
from agnostic_kernel.crypto import hash_token
from agnostic_kernel.domain_events import DomainEvents
from tests.support.saml_idp import TestIdp, decode_authn_request
from tests.support.soft_authenticator import SoftAuthenticator
from tests.support.stack import OWNER_PASSWORD, PUBLIC_URL, Stack, running_stack

OWNER_EMAIL = "daniel@localhost.company"
SAML_ID = "corp-saml"
ACS = f"{PUBLIC_URL}/api/v1/auth/sso/{SAML_ID}/acs"
SP_ENTITY = f"{PUBLIC_URL}/api/v1/auth/sso/{SAML_ID}/metadata"


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


@pytest.fixture(scope="module")
def idp() -> TestIdp:
    return TestIdp()


async def add_saml_provider(owner: httpx.AsyncClient, idp: TestIdp, **extra: Any) -> dict[str, Any]:
    created = await owner.post(
        "/api/v1/auth/admin/providers",
        json={
            "id": SAML_ID,
            "kind": "saml",
            "display_name": "Localhost Company SAML",
            "metadata_xml": idp.metadata(),
            "attribute_mapping": {"email": "email", "name": "displayName", "groups": "groups"},
            "jit_provisioning": True,
            "allowed_email_domains": ["localhost.company"],
            **extra,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def add_member(stack: Stack, owner: httpx.AsyncClient, email: str, password: str) -> httpx.AsyncClient:
    invited = await owner.post("/api/v1/invitations", json={"email": email, "org_role": "member"})
    assert invited.status_code == 201, invited.text
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    client = stack.client()
    joined = await client.post(f"/api/v1/invitations/{token}/accept", json={"display_name": None, "password": password})
    assert joined.status_code == 200, joined.text
    client.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    return client


async def age_authentication(stack: Stack, client: httpx.AsyncClient, minutes: int = 11) -> None:
    """Pretend the person signed in a while ago (step-up needed again)."""
    store = await stack.container.get(SessionStore)
    key = hash_token(client.cookies[SESSION_COOKIE])
    session = await store.load(key)
    assert session is not None
    assert session.authenticated_at is not None
    await store.save(replace(session, authenticated_at=session.authenticated_at - timedelta(minutes=minutes)), 3600)


async def audit_actions(owner: httpx.AsyncClient, action: str) -> list[dict[str, Any]]:
    return (await owner.get("/api/v1/audit/events", params={"action": action})).json()["data"]


async def saml_sign_in(
    client: httpx.AsyncClient, idp: TestIdp, *, name_id: str, attributes: Mapping[str, list[str]], next_path: str = "/"
) -> tuple[httpx.Response, str, str]:
    start = await client.get(f"/api/v1/auth/sso/{SAML_ID}/start", params={"next": next_path})
    assert start.status_code == 302, start.text
    assert start.headers["location"].startswith(f"{idp.sso_url}?SAMLRequest=")
    request, relay_state = decode_authn_request(start.headers["location"])
    response = idp.sign_in(
        request_id=str(request.get("ID")), acs_url=ACS, audience=SP_ENTITY, name_id=name_id, attributes=attributes
    )
    posted = await client.post(
        f"/api/v1/auth/sso/{SAML_ID}/acs",
        data={"SAMLResponse": response, "RelayState": relay_state},
    )
    return posted, response, relay_state


async def test_provider_admin_crud_and_metadata(stack: Stack, idp: TestIdp) -> None:
    owner = await stack.owner()
    saml = await add_saml_provider(owner, idp)
    assert saml["managed_by"] == "database"
    assert saml["saml"]["idp_entity_id"] == idp.entity_id
    assert saml["saml"]["sso_url"] == idp.sso_url
    assert saml["saml"]["sp_entity_id"] == SP_ENTITY
    assert saml["saml"]["acs_url"] == ACS
    assert saml["saml"]["certificates"][0]["subject"] == "CN=Test IdP"
    assert saml["oidc"] is None

    oidc = await owner.post(
        "/api/v1/auth/admin/providers",
        json={
            "id": "okta",
            "kind": "oidc",
            "preset": "okta",
            "issuer": "https://localhost-company.okta.com/oauth2/default",
            "client_id": "0oa-client",
            "client_secret": "very-secret-value",
        },
    )
    assert oidc.status_code == 201, oidc.text
    assert "very-secret-value" not in oidc.text
    assert oidc.json()["oidc"]["has_client_secret"] is True
    assert oidc.json()["oidc"]["callback_url"] == f"{PUBLIC_URL}/api/v1/auth/sso/okta/callback"

    duplicate = await owner.post(
        "/api/v1/auth/admin/providers",
        json={"id": "okta", "kind": "oidc", "issuer": "https://x.test", "client_id": "c"},
    )
    assert duplicate.status_code == 409
    invalid = await owner.post("/api/v1/auth/admin/providers", json={"id": "bad", "kind": "saml"})
    assert invalid.status_code == 422

    listed = (await owner.get("/api/v1/auth/admin/providers")).json()
    assert [item["id"] for item in listed] == [SAML_ID, "okta"]
    public = (await stack.client().get("/api/v1/auth/providers")).json()
    assert public["providers"] == [
        {"id": SAML_ID, "display_name": "Localhost Company SAML", "preset": "saml"},
        {"id": "okta", "display_name": "Okta", "preset": "okta"},
    ]

    metadata = await owner.get(f"/api/v1/auth/admin/providers/{SAML_ID}/saml-metadata")
    assert metadata.status_code == 200
    assert metadata.headers["content-type"].startswith("application/samlmetadata+xml")
    assert f'entityID="{SP_ENTITY}"' in metadata.text
    assert ACS in metadata.text
    assert (await stack.client().get(f"/api/v1/auth/sso/{SAML_ID}/metadata")).status_code == 200

    renamed = await owner.patch(
        "/api/v1/auth/admin/providers/okta", json={"display_name": "Okta (staff)", "client_secret": None}
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["display_name"], renamed.json()["oidc"]["has_client_secret"]) == ("Okta (staff)", False)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://idp.localhost.test/metadata").respond(text=idp.metadata())
        refreshed = await owner.patch(
            f"/api/v1/auth/admin/providers/{SAML_ID}", json={"metadata_url": "https://idp.localhost.test/metadata"}
        )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["saml"]["metadata_url"] == "https://idp.localhost.test/metadata"

    assert (await owner.delete("/api/v1/auth/admin/providers/okta")).status_code == 204
    assert (await owner.get("/api/v1/auth/admin/providers/okta")).status_code == 404
    for action in ("auth.providers.create", "auth.providers.update", "auth.providers.delete"):
        assert await audit_actions(owner, action), action
    update = (await audit_actions(owner, "auth.providers.update"))[-1]
    assert "very-secret-value" not in str(update)

    member = await add_member(stack, owner, "marcus@localhost.company", "marcus's long password")
    denied = await member.get("/api/v1/auth/admin/providers")
    assert (denied.status_code, denied.json()["code"]) == (403, "scope_missing")


async def test_saml_sign_in_end_to_end(stack: Stack, idp: TestIdp) -> None:
    owner = await stack.owner()
    _ = await add_saml_provider(owner, idp)
    attributes = {
        "email": ["Ada@Localhost.company"],
        "displayName": ["Ada Lovelace"],
        "groups": ["Engineering", "Admins"],
    }
    ada = stack.client()
    posted, response, relay_state = await saml_sign_in(
        ada, idp, name_id="okta|00u-ada", attributes=attributes, next_path="/access/people"
    )
    assert posted.status_code == 303, posted.text
    assert posted.headers["location"] == "/access/people"
    me = (await ada.get("/api/v1/me")).json()
    assert (me["email"], me["display_name"], me["org_role"]) == ("ada@localhost.company", "Ada Lovelace", "member")
    assert me["sso_providers"] == [SAML_ID]
    assert me["session_method"] == f"sso:{SAML_ID}"

    async with stack.container() as request:
        session = await request.get(AsyncSession)
        claims = await session.scalar(
            select(ExternalIdentityRow.raw_claims).where(ExternalIdentityRow.provider_id == SAML_ID)
        )
    assert claims is not None
    assert claims["groups"] == ["Engineering", "Admins"]

    # The RelayState is single-use, and an old response doesn't answer a new request.
    replayed = await stack.client().post(
        f"/api/v1/auth/sso/{SAML_ID}/acs", data={"SAMLResponse": response, "RelayState": relay_state}
    )
    assert replayed.headers["location"] == "/login?error=state_expired"
    other = stack.client()
    start = await other.get(f"/api/v1/auth/sso/{SAML_ID}/start")
    _, fresh_state = decode_authn_request(start.headers["location"])
    stale = await other.post(
        f"/api/v1/auth/sso/{SAML_ID}/acs", data={"SAMLResponse": response, "RelayState": fresh_state}
    )
    assert stale.headers["location"] == "/login?error=state_mismatch"

    outsider, _, _ = await saml_sign_in(
        stack.client(), idp, name_id="okta|eve", attributes={"email": ["eve@elsewhere.dev"]}
    )
    assert outsider.headers["location"] == "/login?error=not_invited"
    events = await audit_actions(owner, "auth.login")
    assert any(event["actor"]["id"] == me["id"] for event in events)


async def test_enforce_sso_and_break_glass(stack: Stack, idp: TestIdp, monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[tuple[str, dict[str, Any]]] = []

    async def capture(_self: DomainEvents, event: str, payload: Mapping[str, Any]) -> None:
        published.append((event, dict(payload)))

    monkeypatch.setattr(DomainEvents, "publish", capture)
    owner = await stack.owner()
    owner_id = (await owner.get("/api/v1/me")).json()["id"]
    member = await add_member(stack, owner, "marcus@localhost.company", "marcus's long password")
    marcus_id = (await member.get("/api/v1/me")).json()["id"]

    policy = (await owner.get("/api/v1/auth/admin/policy")).json()
    assert policy["enforce_sso"] is False
    assert policy["mfa_policy"] == "optional"
    assert (policy["default_session_idle_minutes"], policy["default_session_absolute_hours"]) == (720, 168)

    no_provider = await owner.put(
        "/api/v1/auth/admin/policy", json={"enforce_sso": True, "break_glass_user_id": owner_id}
    )
    assert no_provider.status_code == 422
    _ = await add_saml_provider(owner, idp)
    no_break_glass = await owner.put("/api/v1/auth/admin/policy", json={"enforce_sso": True})
    assert no_break_glass.status_code == 422
    not_owner = await owner.put(
        "/api/v1/auth/admin/policy", json={"enforce_sso": True, "break_glass_user_id": marcus_id}
    )
    assert not_owner.status_code == 422
    enforced = await owner.put(
        "/api/v1/auth/admin/policy",
        json={"enforce_sso": True, "break_glass_user_id": owner_id, "session_idle_minutes": 60},
    )
    assert enforced.status_code == 200, enforced.text
    assert enforced.json()["break_glass_user"]["email"] == OWNER_EMAIL
    assert enforced.json()["session_idle_minutes"] == 60
    assert (await stack.client().get("/api/v1/auth/providers")).json()["sso_enforced"] is True

    # An invite link can be forwarded: under enforced SSO the invitee joins through the IdP, not with a password.
    invited = await owner.post("/api/v1/invitations", json={"email": "jonas@localhost.company", "delivery": "link"})
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    by_password = await stack.client().post(
        f"/api/v1/invitations/{token}/accept", json={"display_name": None, "password": "jonas's long password"}
    )
    assert (by_password.status_code, by_password.json()["code"]) == (403, "sso_required")

    refused = await stack.client().post(
        "/api/v1/auth/login", json={"email": "marcus@localhost.company", "password": "marcus's long password"}
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "sso_required")
    wrong = await stack.client().post(
        "/api/v1/auth/login", json={"email": "marcus@localhost.company", "password": "nope"}
    )
    assert wrong.json()["code"] == "invalid_credentials"

    break_glass = await stack.sign_in(OWNER_EMAIL, OWNER_PASSWORD)
    assert (await break_glass.get("/api/v1/me")).status_code == 200
    assert published[-1][0] == "identity.break_glass_used"
    assert published[-1][1]["user_id"] == owner_id
    assert set(published[-1][1]) == {"user_id", "user_name", "ip"}
    assert await audit_actions(owner, "auth.break_glass")
    assert await audit_actions(owner, "auth.policy.update")

    last = await owner.delete(f"/api/v1/auth/admin/providers/{SAML_ID}")
    assert last.status_code == 409


async def test_totp_two_step_sign_in_and_recovery_codes(stack: Stack) -> None:
    owner = await stack.owner()
    setup = (await owner.post("/api/v1/me/mfa/totp/setup")).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/Agnostic:daniel%40localhost.company?") or setup[
        "otpauth_uri"
    ].startswith("otpauth://totp/Agnostic:daniel@localhost.company?")
    key = totp.decode_secret(setup["secret"])
    wrong = await owner.post("/api/v1/me/mfa/totp/confirm", json={"code": "000000"})
    assert wrong.status_code == 422
    confirmed = await owner.post(
        "/api/v1/me/mfa/totp/confirm", json={"code": totp.totp(key, time.time()), "label": "Phone"}
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery_codes = confirmed.json()["recovery_codes"]
    assert len(recovery_codes) == 10
    assert confirmed.json()["factor"]["label"] == "Phone"
    mfa = (await owner.get("/api/v1/me/mfa")).json()
    assert (mfa["policy"], mfa["recovery_codes_left"], len(mfa["factors"])) == ("optional", 10, 1)

    client = stack.client()
    first = await client.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mfa_required"] is True
    assert body["enroll"] is False
    assert body["methods"] == ["totp", "recovery_code"]
    assert SESSION_COOKIE not in client.cookies
    assert (await client.get("/api/v1/me")).status_code == 401

    bad = await client.post("/api/v1/auth/login/mfa", json={"challenge": body["challenge"], "code": "123456"})
    assert (bad.status_code, bad.json()["code"]) == (401, "mfa_invalid")
    # The code from enrollment's time step was used; the next step's code is accepted (one step of drift).
    good = await client.post(
        "/api/v1/auth/login/mfa", json={"challenge": body["challenge"], "code": totp.totp(key, time.time() + 30)}
    )
    assert good.status_code == 200, good.text
    assert good.json()["user"]["email"] == OWNER_EMAIL
    client.headers["X-CSRF-Token"] = good.json()["csrf_token"]
    assert (await client.get("/api/v1/me")).status_code == 200
    again = await client.post("/api/v1/auth/login/mfa", json={"challenge": body["challenge"], "code": "123456"})
    assert again.json()["code"] == "mfa_challenge_expired"

    recovery = stack.client()
    challenge = (
        await recovery.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    ).json()
    used = await recovery.post(
        "/api/v1/auth/login/mfa", json={"challenge": challenge["challenge"], "recovery_code": recovery_codes[0].upper()}
    )
    assert used.status_code == 200, used.text
    reuse = stack.client()
    challenge = (await reuse.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})).json()
    refused = await reuse.post(
        "/api/v1/auth/login/mfa", json={"challenge": challenge["challenge"], "recovery_code": recovery_codes[0]}
    )
    assert refused.json()["code"] == "mfa_invalid"
    assert (await owner.get("/api/v1/me/mfa")).json()["recovery_codes_left"] == 9
    assert await audit_actions(owner, "auth.mfa.enroll")
    assert await audit_actions(owner, "auth.mfa.challenge_failed")

    regenerated = await owner.post("/api/v1/me/mfa/recovery-codes")
    assert len(regenerated.json()["recovery_codes"]) == 10
    factor_id = mfa["factors"][0]["id"]
    assert (await owner.delete(f"/api/v1/me/mfa/{factor_id}")).status_code == 204
    assert (await owner.get("/api/v1/me/mfa")).json() == {
        "policy": "optional",
        "required": False,
        "factors": [],
        "recovery_codes_left": 0,
    }
    plain = await stack.client().post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert "csrf_token" in plain.json()


async def test_required_mfa_enrolls_at_sign_in_with_a_security_key(stack: Stack) -> None:
    owner = await stack.owner()
    policy = await owner.put("/api/v1/auth/admin/policy", json={"mfa_policy": "required_admins"})
    assert policy.status_code == 200, policy.text

    client = stack.client()
    pending = (await client.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})).json()
    assert (pending["mfa_required"], pending["enroll"], pending["methods"]) == (True, True, ["totp", "webauthn"])

    key = SoftAuthenticator()
    creation = await client.post("/api/v1/auth/login/mfa/webauthn/options", json={"challenge": pending["challenge"]})
    assert creation.status_code == 200, creation.text
    signed_in = await client.post(
        "/api/v1/auth/login/mfa",
        json={"challenge": pending["challenge"], "webauthn": key.create(creation.json()), "label": "YubiKey"},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert len(signed_in.json()["recovery_codes"]) == 10
    client.headers["X-CSRF-Token"] = signed_in.json()["csrf_token"]
    factors = (await client.get("/api/v1/me/mfa")).json()
    assert factors["required"] is True
    assert [(item["kind"], item["label"]) for item in factors["factors"]] == [("webauthn", "YubiKey")]

    # Next time the key answers the challenge.
    second = stack.client()
    pending = (await second.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})).json()
    assert pending["methods"] == ["webauthn", "recovery_code"]
    request = await second.post("/api/v1/auth/login/mfa/webauthn/options", json={"challenge": pending["challenge"]})
    assertion = key.get(request.json())
    done = await second.post("/api/v1/auth/login/mfa", json={"challenge": pending["challenge"], "webauthn": assertion})
    assert done.status_code == 200, done.text
    assert done.json()["recovery_codes"] == []

    # The last factor can't go while the policy requires one.
    factor_id = factors["factors"][0]["id"]
    blocked = await client.delete(f"/api/v1/me/mfa/{factor_id}")
    assert blocked.status_code == 409


async def test_step_up_gates_sensitive_changes(stack: Stack, idp: TestIdp) -> None:
    owner = await stack.owner()
    status = (await owner.get("/api/v1/auth/step-up")).json()
    assert (status["recent"], status["methods"]) == (True, ["password"])

    await age_authentication(stack, owner)
    assert (await owner.get("/api/v1/auth/step-up")).json()["recent"] is False
    gated = await owner.post(
        "/api/v1/auth/admin/providers", json={"id": SAML_ID, "kind": "saml", "metadata_xml": idp.metadata()}
    )
    assert (gated.status_code, gated.json()["code"]) == (403, "reauth_required")
    assert (await owner.put("/api/v1/auth/admin/policy", json={"mfa_policy": "off"})).json()[
        "code"
    ] == "reauth_required"

    failed = await owner.post("/api/v1/auth/step-up", json={"password": "not my password"})
    assert (failed.status_code, failed.json()["code"]) == (422, "step_up_failed")
    stepped = await owner.post("/api/v1/auth/step-up", json={"password": OWNER_PASSWORD})
    assert stepped.status_code == 200, stepped.text
    assert stepped.json()["recent"] is True
    _ = await add_saml_provider(owner, idp)
    assert await audit_actions(owner, "auth.step_up")
    assert await audit_actions(owner, "auth.step_up_failed")

    # An authenticator code works too.
    secret = (await owner.post("/api/v1/me/mfa/totp/setup")).json()["secret"]
    key = totp.decode_secret(secret)
    _ = await owner.post("/api/v1/me/mfa/totp/confirm", json={"code": totp.totp(key, time.time())})
    await age_authentication(stack, owner)
    by_code = await owner.post("/api/v1/auth/step-up", json={"code": totp.totp(key, time.time() + 30)})
    assert by_code.status_code == 200, by_code.text
    assert set((await owner.get("/api/v1/auth/step-up")).json()["methods"]) == {"password", "totp"}
