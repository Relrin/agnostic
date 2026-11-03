"""Directory sync end to end: SCIM as Okta and Entra ID drive it, Google Workspace, mapping rules and login claims."""

import secrets
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_directory.application.reconcile import Reconcile
from agnostic_identity.facade import IdentityFacade, UserStatus
from tests.api.test_governance import invite, roles_by_slug
from tests.api.test_instances_gateway import connect
from tests.api.test_sso import Idp, sso_sign_in
from tests.support.stack import Stack, running_stack

SCIM = "/scim/v2"
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
ISSUER = "https://sso.localhost.test"


@pytest.fixture(scope="module")
def idp_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    env = {
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__PRESET": "oidc",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__DISPLAY_NAME": "Localhost Company SSO",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__ISSUER": ISSUER,
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__CLIENT_ID": "agnostic",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__CLIENT_SECRET": "s3cret",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__JIT_PROVISIONING": "true",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__ALLOWED_EMAIL_DOMAINS": "localhost.company",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    async with running_stack(sqlite_database) as running:
        yield running


async def scim_client(stack: Stack, owner: httpx.AsyncClient, label: str) -> httpx.AsyncClient:
    issued = await owner.post("/api/v1/directory/scim/tokens", json={"label": label})
    assert issued.status_code == 201, issued.text
    client = stack.client()
    client.headers["Authorization"] = f"Bearer {issued.json()['secret']}"
    return client


def ops(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": [PATCH_SCHEMA], "Operations": list(operations)}


def okta_user(email: str, given: str, family: str) -> dict[str, Any]:
    """What Okta's SCIM 2.0 app sends on "Push new users" (the password only when password sync is on)."""
    return {
        "schemas": [USER_SCHEMA],
        "userName": email,
        "name": {"givenName": given, "familyName": family},
        "emails": [{"primary": True, "value": email, "type": "work"}],
        "displayName": f"{given} {family}",
        "locale": "en-US",
        "externalId": f"00u{secrets.token_hex(4)}",
        "groups": [],
        "password": secrets.token_urlsafe(12),
        "active": True,
    }


async def audit_actors(owner: httpx.AsyncClient, action: str) -> list[str]:
    events = (await owner.get("/api/v1/audit/events", params={"action": action})).json()["data"]
    return [event["actor"]["display"] for event in events]


async def test_scim_requires_its_own_bearer_token(stack: Stack) -> None:
    owner = await stack.owner()
    anonymous = await stack.client().get(f"{SCIM}/Users")
    assert anonymous.status_code == 401
    assert anonymous.headers["content-type"].startswith("application/scim+json")
    assert anonymous.json()["schemas"] == [ERROR_SCHEMA]
    # A web session is not a SCIM credential.
    assert (await owner.get(f"{SCIM}/Users")).status_code == 401
    forged = await stack.client().get(f"{SCIM}/Users", headers={"Authorization": f"Bearer agn_scim_{'x' * 43}"})
    assert forged.status_code == 401


async def test_tokens_are_shown_once_rotated_and_revoked(stack: Stack) -> None:
    owner = await stack.owner()
    first = await owner.post("/api/v1/directory/scim/tokens", json={"label": "Okta SCIM"})
    assert first.status_code == 201
    secret = first.json()["secret"]
    assert secret.startswith("agn_scim_")
    assert first.json()["token"]["prefix"] == secret[:13]
    second = await owner.post("/api/v1/directory/scim/tokens", json={"label": "Another"})
    assert second.status_code == 409

    status = (await owner.get("/api/v1/directory/scim")).json()
    assert status["endpoint_url"] == "http://agnostic.test/scim/v2"
    assert [(t["label"], t["state"]) for t in status["tokens"]] == [("Okta SCIM", "active")]
    assert secret not in str(status)

    old_id = first.json()["token"]["id"]
    rotated = await owner.post(f"/api/v1/directory/scim/tokens/{old_id}/rotate")
    assert rotated.status_code == 201
    new_secret = rotated.json()["secret"]
    assert rotated.json()["token"]["rotated_from"] == old_id
    tokens = {t["id"]: t for t in (await owner.get("/api/v1/directory/scim")).json()["tokens"]}
    assert tokens[old_id]["state"] == "rotating"
    assert tokens[old_id]["expires_at"] is not None

    client = stack.client()
    for token in (secret, new_secret):  # both work during the rotation window
        found = await client.get(f"{SCIM}/ServiceProviderConfig", headers={"Authorization": f"Bearer {token}"})
        assert found.status_code == 200, found.text
        assert found.json()["patch"] == {"supported": True}

    assert (await owner.delete(f"/api/v1/directory/scim/tokens/{old_id}")).status_code == 204
    revoked = await client.get(f"{SCIM}/Users", headers={"Authorization": f"Bearer {secret}"})
    assert revoked.status_code == 401
    assert await audit_actors(owner, "directory.scim.token.*") == ["Daniel Okafor"] * 3


async def test_okta_provisioning_lifecycle(stack: Stack, idp_key: rsa.RSAPrivateKey) -> None:  # noqa: PLR0915
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)
    okta = await scim_client(stack, owner, "Okta SCIM")

    # Okta's "Test connector configuration" and import calls.
    assert (await okta.get(f"{SCIM}/ServiceProviderConfig")).status_code == 200
    types = (await okta.get(f"{SCIM}/ResourceTypes")).json()
    assert {resource["name"] for resource in types["Resources"]} == {"User", "Group"}
    assert (await okta.get(f"{SCIM}/Schemas/{USER_SCHEMA}")).json()["name"] == "User"
    first_page = (await okta.get(f"{SCIM}/Users", params={"startIndex": 1, "count": 2})).json()
    assert first_page["totalResults"] == 1  # the Owner
    assert first_page["Resources"][0]["userName"] == "daniel@localhost.company"

    # Push a new user: look up, create, read back.
    lookup = await okta.get(
        f"{SCIM}/Users", params={"filter": 'userName eq "maya@localhost.company"', "startIndex": 1, "count": 100}
    )
    assert lookup.json() == {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 0,
        "startIndex": 1,
        "itemsPerPage": 0,
        "Resources": [],
    }
    created = await okta.post(f"{SCIM}/Users", json=okta_user("maya@localhost.company", "Maya", "Chen"))
    assert created.status_code == 201, created.text
    assert created.headers["content-type"].startswith("application/scim+json")
    maya_id = created.json()["id"]
    assert created.headers["location"] == f"http://agnostic.test/scim/v2/Users/{maya_id}"
    assert created.json()["active"] is True
    assert created.json()["displayName"] == "Maya Chen"
    assert "password" not in created.json()
    duplicate = await okta.post(f"{SCIM}/Users", json=okta_user("maya@localhost.company", "Maya", "Chen"))
    assert (duplicate.status_code, duplicate.json()["scimType"]) == (409, "uniqueness")
    found = await okta.get(f"{SCIM}/Users", params={"filter": 'userName eq "Maya@Localhost.company"'})
    assert [user["id"] for user in found.json()["Resources"]] == [maya_id]
    member = (await owner.get(f"/api/v1/members/{maya_id}")).json()
    assert member["org_role"] == "member"
    assert await audit_actors(owner, "scim.users.create") == ["Okta SCIM"]

    # The hand-made group that holds the Operator binding, made before the IdP pushes its group.
    manual = await owner.post("/api/v1/directory/groups", json={"name": "Support AI"})
    manual_id = manual.json()["id"]
    roles = await roles_by_slug(owner)
    bound = await owner.post(
        "/api/v1/access/bindings",
        json={
            "principal_kind": "group",
            "principal_id": manual_id,
            "instance": "prod-agentos",
            "role_id": roles["operator"]["id"],
        },
    )
    assert bound.status_code == 201, bound.text
    direct = await owner.post(
        "/api/v1/access/bindings",
        json={"principal_kind": "user", "principal_id": maya_id, "role_id": roles["viewer"]["id"]},
    )
    assert direct.status_code == 201, direct.text

    # Push groups: create empty, then add members (Okta's two-step push).
    pushed = await okta.post(f"{SCIM}/Groups", json={"schemas": [GROUP_SCHEMA], "displayName": "support-ai"})
    assert pushed.status_code == 201, pushed.text
    scim_group = pushed.json()["id"]
    added = await okta.patch(
        f"{SCIM}/Groups/{scim_group}",
        json=ops({"op": "add", "path": "members", "value": [{"value": maya_id, "display": "maya@localhost.company"}]}),
    )
    assert added.status_code == 200, added.text
    assert [m["value"] for m in added.json()["members"]] == [maya_id]
    assert added.json()["displayName"] == "support-ai"
    names = {g["name"] for g in (await owner.get("/api/v1/directory/groups")).json()}
    assert names == {"Support AI", "support-ai (SCIM)"}

    # A mapping rule carries the SCIM group into it.
    rule = await owner.post(
        "/api/v1/directory/mapping-rules", json={"source": "scim", "idp_group": "support-ai", "group_id": manual_id}
    )
    assert rule.status_code == 201, rule.text
    assert rule.json()["group_name"] == "Support AI"
    detail = (await owner.get(f"/api/v1/directory/groups/{manual_id}")).json()
    assert [(m["user_id"], m["source"]) for m in detail["members"]] == [(maya_id, "scim")]

    with respx.mock(assert_all_called=False) as router:
        idp = Idp(router, idp_key)
        idp.claims = {"sub": "kc-maya", "email": "maya@localhost.company", "name": "Maya Chen"}
        maya = stack.client()
        assert (await sso_sign_in(maya, idp)).headers["location"] == "/"
        access = (await maya.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()
        assert "Operator" in access["roles"]

        # Okta deactivates her: sessions, bindings and groups go at once; she can't sign in again.
        off = await okta.patch(f"{SCIM}/Users/{maya_id}", json=ops({"op": "replace", "value": {"active": False}}))
        assert off.status_code == 200, off.text
        assert off.json()["active"] is False
        assert (await maya.get("/api/v1/me")).status_code == 401
        assert (await maya.get("/api/v1/me/access")).status_code == 401
        retry = await sso_sign_in(stack.client(), idp)
        assert retry.headers["location"] == "/login?error=account_disabled"

    assert (await owner.get("/api/v1/access/bindings", params={"principal": maya_id})).json() == []
    assert (await owner.get(f"/api/v1/directory/groups/{manual_id}")).json()["members"] == []
    assert (await okta.get(f"{SCIM}/Groups/{scim_group}")).json()["members"] == []
    assert (await okta.get(f"{SCIM}/Users/{maya_id}")).json()["active"] is False
    # "disable" (the default) keeps the org membership for a reactivation.
    assert (await owner.get(f"/api/v1/members/{maya_id}")).status_code == 200
    assert await audit_actors(owner, "scim.users.deactivate") == ["Okta SCIM"]
    assert "Okta SCIM" in await audit_actors(owner, "bindings.delete")

    status = (await owner.get("/api/v1/directory/scim")).json()
    assert status["last_request_at"] is not None
    assert status["healthy"] is True
    assert status["counts"] == {"users": 0, "deactivated_users": 1, "groups": 1}

    on = await okta.patch(f"{SCIM}/Users/{maya_id}", json=ops({"op": "replace", "value": {"active": True}}))
    assert on.json()["active"] is True
    assert await audit_actors(owner, "scim.users.reactivate") == ["Okta SCIM"]

    # A failed request shows up on the status pill.
    bad = await okta.get(f"{SCIM}/Users", params={"filter": "userName eq"})
    assert (bad.status_code, bad.json()["scimType"]) == (400, "invalidFilter")
    status = (await owner.get("/api/v1/directory/scim")).json()
    assert status["healthy"] is False
    assert "400" in status["last_error"]


async def test_entra_id_provisioning_sequence(stack: Stack) -> None:
    owner = await stack.owner()
    entra = await scim_client(stack, owner, "Entra ID")
    external_id = "8c2f3d4e-ana"

    absent = await entra.get(f"{SCIM}/Users", params={"filter": f'externalId eq "{external_id}"'})
    assert absent.json()["totalResults"] == 0
    created = await entra.post(
        f"{SCIM}/Users",
        json={
            "schemas": [USER_SCHEMA, ENTERPRISE],
            "externalId": external_id,
            "userName": "ana.silva@localhost.company",
            "active": True,
            "displayName": "Ana Silva",
            "emails": [{"primary": True, "type": "work", "value": "ana.silva@localhost.company"}],
            "name": {"formatted": "Ana Silva", "familyName": "Silva", "givenName": "Ana"},
            ENTERPRISE: {"employeeNumber": "1042", "department": "Support"},
        },
    )
    assert created.status_code == 201, created.text
    ana_id = created.json()["id"]
    by_external = await entra.get(f"{SCIM}/Users", params={"filter": f'externalId eq "{external_id}"'})
    assert [user["id"] for user in by_external.json()["Resources"]] == [ana_id]
    assert by_external.json()["Resources"][0][ENTERPRISE]["department"] == "Support"

    # Entra's PATCH: capitalized ops, string booleans, filtered paths, dotted sub-attributes.
    disabled = await entra.patch(
        f"{SCIM}/Users/{ana_id}", json=ops({"op": "Replace", "path": "active", "value": "False"})
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["active"] is False
    enabled = await entra.patch(
        f"{SCIM}/Users/{ana_id}",
        json=ops(
            {"op": "Replace", "path": "active", "value": "True"},
            {"op": "Replace", "path": "displayName", "value": "Ana Sofia Silva"},
            {"op": "Replace", "path": "name.givenName", "value": "Ana Sofia"},
            {"op": "Add", "path": 'emails[type eq "work"].value', "value": "ana.silva@localhost.company"},
            {"op": "Add", "path": f"{ENTERPRISE}:department", "value": "Escalations"},
        ),
    )
    assert enabled.status_code == 200, enabled.text
    body = enabled.json()
    assert body["active"] is True
    assert body["displayName"] == "Ana Sofia Silva"
    assert body["name"]["givenName"] == "Ana Sofia"
    assert body[ENTERPRISE]["department"] == "Escalations"
    assert (await owner.get(f"/api/v1/members/{ana_id}")).json()["display_name"] == "Ana Sofia Silva"

    # Groups: look up by displayName without members, create, add, remove through a filtered path.
    lookup = await entra.get(
        f"{SCIM}/Groups", params={"filter": 'displayName eq "Tier 2"', "excludedAttributes": "members"}
    )
    assert lookup.json()["totalResults"] == 0
    group = await entra.post(
        f"{SCIM}/Groups", json={"schemas": [GROUP_SCHEMA], "externalId": "g-tier2", "displayName": "Tier 2"}
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    assert group.json()["externalId"] == "g-tier2"
    added = await entra.patch(
        f"{SCIM}/Groups/{group_id}", json=ops({"op": "Add", "path": "members", "value": [{"value": ana_id}]})
    )
    assert [m["value"] for m in added.json()["members"]] == [ana_id]
    slim = await entra.get(f"{SCIM}/Groups/{group_id}", params={"excludedAttributes": "members"})
    assert "members" not in slim.json()
    removed = await entra.patch(
        f"{SCIM}/Groups/{group_id}", json=ops({"op": "Remove", "path": f'members[value eq "{ana_id}"]'})
    )
    assert removed.json()["members"] == []
    renamed = await entra.patch(
        f"{SCIM}/Groups/{group_id}",
        json=ops({"op": "Replace", "path": "displayName", "value": "Tier 2 Support"}),
    )
    assert renamed.json()["displayName"] == "Tier 2 Support"
    listed = {g["name"]: g for g in (await owner.get("/api/v1/directory/groups")).json()}
    assert listed["Tier 2 Support"]["sync_label"] == "SCIM · Tier 2 Support"

    # Hard delete: gone from SCIM and from the org.
    assert (await entra.delete(f"{SCIM}/Groups/{group_id}")).status_code == 204
    assert (await entra.delete(f"{SCIM}/Users/{ana_id}")).status_code == 204
    gone = await entra.get(f"{SCIM}/Users/{ana_id}")
    assert (gone.status_code, gone.json()["schemas"]) == (404, [ERROR_SCHEMA])
    assert (await owner.get(f"/api/v1/members/{ana_id}")).status_code == 404
    assert await audit_actors(owner, "scim.groups.*") == ["Entra ID"] * 5
    assert await audit_actors(owner, "scim.users.delete") == ["Entra ID"]


async def test_remove_behaviour_and_reconcile(stack: Stack) -> None:
    owner = await stack.owner()
    okta = await scim_client(stack, owner, "Okta SCIM")
    changed = await owner.put("/api/v1/directory/settings", json={"deprovision": "remove"})
    assert changed.json() == {"deprovision": "remove"}
    assert (await owner.get("/api/v1/directory/settings")).json() == {"deprovision": "remove"}

    created = await okta.post(f"{SCIM}/Users", json=okta_user("omar@localhost.company", "Omar", "Haddad"))
    omar_id = created.json()["id"]
    put = {**okta_user("omar@localhost.company", "Omar", "Haddad"), "active": False}
    off = await okta.put(f"{SCIM}/Users/{omar_id}", json=put)
    assert off.json()["active"] is False
    assert (await owner.get(f"/api/v1/members/{omar_id}")).status_code == 404
    assert (await okta.get(f"{SCIM}/Users/{omar_id}")).json()["active"] is False
    back = await okta.put(f"{SCIM}/Users/{omar_id}", json={**put, "active": True})
    assert back.json()["active"] is True
    assert (await owner.get(f"/api/v1/members/{omar_id}")).status_code == 200

    # The only Owner can't be deprovisioned through SCIM.
    owner_id = (await owner.get("/api/v1/me")).json()["id"]
    refused = await okta.patch(f"{SCIM}/Users/{owner_id}", json=ops({"op": "replace", "value": {"active": False}}))
    assert refused.status_code == 409

    # Reconcile takes deprovisioned accounts out of groups a failed request left them in.
    _, lee_id = await invite(stack, owner, "lee@localhost.company", "Lee Park")
    group = await owner.post("/api/v1/directory/groups", json={"name": "Night shift", "member_ids": [lee_id]})
    async with stack.container() as request:
        identity = await request.get(IdentityFacade)
        _ = await identity.set_status(lee_id, UserStatus.DEPROVISIONED)
        await (await request.get(AsyncSession)).commit()
    async with stack.container() as request:
        result = await (await request.get(Reconcile))()
    assert result.removed_memberships == 1
    assert (await owner.get(f"/api/v1/directory/groups/{group.json()['id']}")).json()["members"] == []


async def test_google_workspace_sync(stack: Stack) -> None:  # noqa: PLR0915
    owner = await stack.owner()
    _, maya_id = await invite(stack, owner, "maya@localhost.company", "Maya Chen")
    _, joe_id = await invite(stack, owner, "joe@localhost.company", "Joe Rivera")
    google = stack.google
    google.add_user("admin@localhost.company", "Workspace Admin")
    google.add_user("daniel@localhost.company", "Daniel Okafor")
    google.add_user("maya.chen@localhost.company", "Maya Chen", aliases=("maya@localhost.company",))
    google.add_user("joe@localhost.company", "Joe Rivera", suspended=True)
    google.add_group(
        "00g1", "support-ai@localhost.company", "Support AI", ["maya.chen@localhost.company", "temp@agency.test"]
    )
    google.add_group("00g2", "sales@localhost.company", "Sales", ["daniel@localhost.company"])
    google.add_group("00g3", "support-tier2@localhost.company", "Tier 2", ["daniel@localhost.company"])

    untested = await owner.post("/api/v1/directory/google/test")
    assert untested.json()["ok"] is False
    configured = await owner.put(
        "/api/v1/directory/google",
        json={
            "service_account_json": google.service_account_json(),
            "admin_subject": "admin@localhost.company",
            "group_filter": ["support*"],
            "enabled": True,
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["client_email"] == google.client_email
    assert "PRIVATE KEY" not in configured.text
    assert "PRIVATE KEY" not in (await owner.get("/api/v1/directory/google")).text

    tested = (await owner.post("/api/v1/directory/google/test")).json()
    assert tested == {"ok": True, "detail": "Connected as admin@localhost.company; 2 of 3 groups match the filter."}
    assert google.token_requests  # the token came from Google's fixed endpoint, not the key file's token_uri

    synced = await owner.post("/api/v1/directory/google/sync")
    assert synced.status_code == 200, synced.text
    assert synced.json()["counts"] == {
        "groups": 2,
        "memberships": 2,
        "unmatched": 1,
        "deprovisioned": 1,
        "users": 4,
    }
    assert synced.json()["last_error"] is None
    groups = {g["name"]: g for g in (await owner.get("/api/v1/directory/groups")).json()}
    assert set(groups) == {"Support AI", "Tier 2"}
    assert groups["Support AI"]["source"] == "google_directory"
    assert groups["Support AI"]["sync_label"] == "Google Workspace · support-ai@localhost.company"
    support = (await owner.get(f"/api/v1/directory/groups/{groups['Support AI']['id']}")).json()
    assert [m["user_id"] for m in support["members"]] == [maya_id]
    # Joe is suspended in Google: deprovisioned here.
    async with stack.container() as request:
        joe = await (await request.get(IdentityFacade)).get_user(joe_id)
    assert joe is not None
    assert joe.status is UserStatus.DEPROVISIONED
    refused = await stack.client().post(
        "/api/v1/auth/login", json={"email": "joe@localhost.company", "password": "Joe Rivera's long password"}
    )
    assert refused.status_code == 401
    assert await audit_actors(owner, "directory.users.deprovision") == ["Google Workspace"]

    # Maya leaves the Google group: the next sync takes her out.
    google.members["00g1"] = []
    again = (await owner.post("/api/v1/directory/google/sync")).json()
    assert again["counts"]["memberships"] == 1
    support = (await owner.get(f"/api/v1/directory/groups/{groups['Support AI']['id']}")).json()
    assert support["members"] == []

    # Revoked delegation: the run fails, the error is kept, nothing changes.
    google.revoke_tokens()
    google.admin = "someone-else@localhost.company"
    failed = (await owner.post("/api/v1/directory/google/sync")).json()
    assert failed["last_error"].startswith("Google refused the Directory API call (Invalid Credentials)")
    retried = (await owner.post("/api/v1/directory/google/sync")).json()
    assert retried["last_error"] == "Google refused the service account: Client is unauthorized."
    assert retried["counts"] == again["counts"]
    assert await audit_actors(owner, "directory.google.update") == ["Daniel Okafor"]


async def test_login_claims_fill_claim_groups_and_mapped_groups(stack: Stack, idp_key: rsa.RSAPrivateKey) -> None:
    owner = await stack.owner()
    manual = (await owner.post("/api/v1/directory/groups", json={"name": "Support AI"})).json()
    rule = await owner.post(
        "/api/v1/directory/mapping-rules",
        json={"source": "oidc_claim", "provider_id": "corp", "idp_group": "support-ai", "group_id": manual["id"]},
    )
    assert rule.status_code == 201, rule.text
    synced_target = await owner.post(
        "/api/v1/directory/mapping-rules",
        json={"source": "scim", "idp_group": "x", "group_id": "grp_missing"},
    )
    assert synced_target.status_code == 422

    with respx.mock(assert_all_called=False) as router:
        idp = Idp(router, idp_key)
        idp.claims = {
            "sub": "kc-lee",
            "email": "lee@localhost.company",
            "name": "Lee Park",
            "groups": ["/support-ai", "eng"],
        }
        lee = stack.client()
        assert (await sso_sign_in(lee, idp)).headers["location"] == "/"
        lee_id = (await lee.get("/api/v1/me")).json()["id"]
        groups = {g["name"]: g for g in (await owner.get("/api/v1/directory/groups")).json()}
        # "Support AI" already exists, so the claim group is named after its provider.
        assert groups["support-ai (corp)"]["source"] == "oidc_claim"
        assert groups["eng"]["source"] == "oidc_claim"
        detail = (await owner.get(f"/api/v1/directory/groups/{manual['id']}")).json()
        assert [(m["user_id"], m["source"]) for m in detail["members"]] == [(lee_id, "oidc_claim")]

        idp.claims = {**idp.claims, "groups": ["eng"]}
        assert (await sso_sign_in(stack.client(), idp)).headers["location"] == "/"
        assert (await owner.get(f"/api/v1/directory/groups/{manual['id']}")).json()["members"] == []

    rules = (await owner.get("/api/v1/directory/mapping-rules")).json()
    assert [(r["idp_group"], r["group_name"], r["provider_id"]) for r in rules] == [
        ("support-ai", "Support AI", "corp")
    ]
    assert (await owner.delete(f"/api/v1/directory/mapping-rules/{rules[0]['id']}")).status_code == 204
    assert (await owner.get("/api/v1/directory/mapping-rules")).json() == []
