"""A minimal AgentOS (no db, no models called) and RS256 tokens shaped like the control plane's."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from agno.os import AgentOS
from agno.os.auth import create_dev_token
from agno.workflow import Workflow
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

OS_ID = "bridge-test-os"
ISSUER = "http://localhost:5173"


def _noop(step_input: object) -> str:
    return "ok"


def make_os(**kwargs: object) -> AgentOS:
    """AgentOS needs at least one component; a plain-function workflow needs no model and no db."""
    return AgentOS(id=OS_ID, workflows=[Workflow(id="noop", name="noop", steps=[_noop])], telemetry=False, **kwargs)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture
def mint(key_pair: tuple[str, str]) -> Callable[..., str]:
    """Mint a token the way the control plane does: RS256, aud = os_id, iss, scopes list, 5-minute expiry, kid."""
    private_pem, _ = key_pair

    def _mint(scopes: list[str], *, audience: str = OS_ID, sub: str = "agnostic-system") -> str:
        return create_dev_token(
            sub,
            secret=private_pem,
            scopes=scopes,
            audience=audience,
            expires_in=300,
            algorithm="RS256",
            extra_claims={"iss": ISSUER},
        )

    return _mint


@pytest.fixture(autouse=True)
def _fresh_coding_runtime() -> object:
    """``install()`` configures the process's coding runtime; every test starts from a new one."""
    from agnostic_bridge.coding import _runtime

    _runtime._runtime = None
    yield
    _runtime._runtime = None
