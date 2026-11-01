"""The runtime serves agnostic-bridge, and verifies control-plane tokens (RS256, aud = runtime id) when keyed.

No database or Redis is needed: the app is exercised without running its lifespan.
"""

from collections.abc import Iterator

import pytest
from agno.os.auth import create_dev_token
from agnostic_bridge import install
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.main import app, build_agent_os
from app.settings import RuntimeSettings

PATH = "/agnostic/v1/capabilities"


def test_reports_the_reference_recipe() -> None:
    body = TestClient(app).get(PATH).json()
    features = body["features"]
    assert body["os_id"] == "dev-prod"
    assert features["tracing"] is True
    assert features["scheduler"] is True
    assert features["registry"] is True
    assert features["components"] is True
    assert features["queue"]["durable"] is True
    assert features["queue"]["redis_configured"] is True


def test_user_isolation_defaults_on_for_prod_only() -> None:
    assert RuntimeSettings(id="dev-prod").user_isolation_enabled is True
    assert RuntimeSettings(id="dev-staging").user_isolation_enabled is False
    assert RuntimeSettings(id="dev-staging", user_isolation=True).user_isolation_enabled is True
    assert RuntimeSettings(id="dev-prod", user_isolation=False).user_isolation_enabled is False


@pytest.fixture
def private_pem(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    monkeypatch.setenv("JWT_VERIFICATION_KEY", public_pem.decode())
    yield key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _token(private_pem: str, scopes: list[str], audience: str, issuer: str = "http://localhost:5173") -> str:
    return create_dev_token(
        "agnostic-system",
        secret=private_pem,
        scopes=scopes,
        audience=audience,
        expires_in=300,
        algorithm="RS256",
        extra_claims={"iss": issuer},
    )


def test_jwt_mode_needs_config_read_for_this_runtime(private_pem: str) -> None:
    settings = RuntimeSettings(id="dev-staging", port=7778, jwt_issuer="http://localhost:5173")
    client = TestClient(install(build_agent_os(settings)))

    def get(token: str) -> int:
        return client.get(PATH, headers={"Authorization": f"Bearer {token}"}).status_code

    assert client.get("/info").json()["auth_mode"] == "jwt"
    assert client.get(PATH).status_code == 401
    assert get(_token(private_pem, ["config:read"], "dev-staging")) == 200
    assert get(_token(private_pem, ["agents:read"], "dev-staging")) == 403
    assert get(_token(private_pem, ["config:read"], "dev-prod")) == 401  # minted for another instance
    assert get(_token(private_pem, ["config:read"], "dev-staging", issuer="https://elsewhere")) == 401
