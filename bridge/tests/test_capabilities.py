"""GET /agnostic/v1/capabilities on a minimal AgentOS: payload, auth and scope enforcement, route placement."""

from __future__ import annotations

import platform
from collections.abc import Callable

import agno
import pytest
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.registry import Registry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Match, Mount

from agnostic_bridge import SCOPE_MAPPINGS, __version__, install
from tests.conftest import OS_ID, make_os

PATH = "/agnostic/v1/capabilities"


def _secured_os(public_pem: str, **kwargs: object) -> AgentOS:
    authorization = Authorization(
        verification_keys=[public_pem], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    return make_os(authorization=authorization, **kwargs)


def test_open_os_reports_versions_and_features() -> None:
    app = install(make_os(registry=Registry()), replica_id="replica-a")

    response = TestClient(app).get(PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["bridge_version"] == __version__
    assert body["api_version"] == "v1"
    assert body["agno_version"] == agno.__version__
    assert body["python_version"] == platform.python_version()
    assert body["os_id"] == OS_ID
    assert body["replica_id"] == "replica-a"
    assert body["endpoints"] == [
        f"GET {PATH}",
        "GET /agnostic/v1/events",
        "GET /agnostic/v1/files/provenance",
        "GET /agnostic/v1/introspect/components",
        "GET /agnostic/v1/registry/{type}/{name}/source",
        "GET /agnostic/v1/workers",
        "POST /agnostic/v1/cel/evaluate",
        "POST /agnostic/v1/components/normalize",
        "POST /agnostic/v1/components/validate",
        "POST /agnostic/v1/evals/run",
    ]
    features = body["features"]
    assert features["auth_mode"] == "none"
    assert features["authorization"] is False
    assert features["user_isolation"] is False
    assert features["registry"] is True
    assert features["db"] is False
    assert features["components"] is False
    assert features["mcp"] is False
    assert features["queue"] == {
        "configured": False,
        "durable": False,
        "redis_configured": False,
        "max_concurrency": None,
    }


def test_replica_id_defaults_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGNOSTIC_BRIDGE_REPLICA_ID", "pod-7")
    app = install(make_os())
    assert TestClient(app).get(PATH).json()["replica_id"] == "pod-7"


def test_registers_scope_mapping_on_the_agentos_table(key_pair: tuple[str, str]) -> None:
    app = install(_secured_os(key_pair[1]))
    mappings = app.state.scope_mappings
    assert mappings[f"GET {PATH}"] == ["config:read"]
    assert "GET /config" in mappings  # the AgentOS table itself, extended in place
    assert set(SCOPE_MAPPINGS) <= set(mappings)


@pytest.mark.parametrize(
    ("scopes", "status"),
    [
        (["config:read"], 200),
        (["agent_os:admin"], 200),
        (["agents:read", "sessions:read"], 403),
        ([], 403),
    ],
)
def test_needs_config_read(key_pair: tuple[str, str], mint: Callable[..., str], scopes: list[str], status: int) -> None:
    client = TestClient(install(_secured_os(key_pair[1])))
    response = client.get(PATH, headers={"Authorization": f"Bearer {mint(scopes)}"})
    assert response.status_code == status, response.text


def test_rejects_anonymous_and_wrong_audience(key_pair: tuple[str, str], mint: Callable[..., str]) -> None:
    client = TestClient(install(_secured_os(key_pair[1])))
    assert client.get(PATH).status_code == 401
    other_os_token = mint(["config:read"], audience="some-other-os")
    assert client.get(PATH, headers={"Authorization": f"Bearer {other_os_token}"}).status_code == 401


def test_jwt_mode_is_reported(key_pair: tuple[str, str], mint: Callable[..., str]) -> None:
    client = TestClient(install(_secured_os(key_pair[1], user_isolation=True)))
    body = client.get(PATH, headers={"Authorization": f"Bearer {mint(['config:read'])}"}).json()
    assert body["features"]["auth_mode"] == "jwt"
    assert body["features"]["authorization"] is True
    assert body["features"]["user_isolation"] is True


def test_sits_ahead_of_the_mcp_catch_all(key_pair: tuple[str, str], mint: Callable[..., str]) -> None:
    app = install(_secured_os(key_pair[1], mcp=True))

    scope = {"type": "http", "method": "GET", "path": PATH, "root_path": "", "path_params": {}}
    routes = app.router.routes
    bridge = next(i for i, route in enumerate(routes) if route.matches(scope)[0] == Match.FULL)
    mcp_mount = next(i for i, route in enumerate(routes) if isinstance(route, Mount))
    assert bridge < mcp_mount

    response = TestClient(app).get(PATH, headers={"Authorization": f"Bearer {mint(['config:read'])}"})
    assert response.status_code == 200
    assert response.json()["features"]["mcp"] is True


def test_works_with_a_base_app() -> None:
    base = FastAPI()

    @base.get("/custom")
    async def custom() -> dict[str, bool]:
        return {"ok": True}

    agent_os = make_os(base_app=base)
    app = install(agent_os)

    assert app is base
    client = TestClient(app)
    assert client.get(PATH).status_code == 200
    assert client.get("/custom").json() == {"ok": True}


def test_listed_in_openapi() -> None:
    app = install(make_os())
    assert PATH in app.openapi()["paths"]
    hidden = install(make_os(), include_in_schema=False)
    assert PATH not in hidden.openapi()["paths"]
