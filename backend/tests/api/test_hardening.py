"""Security headers, metrics, the bundled web app and guides, and client certificates for runtimes."""

import datetime as dt
from collections.abc import AsyncIterator
from pathlib import Path

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from agnostic_kernel.crypto import SecretBox, encode_local_key
from agnostic_kernel.security_headers import content_security_policy
from tests.api.test_instances_gateway import connect
from tests.support.stack import Stack, running_stack


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


@pytest.fixture
def site(tmp_path: Path) -> tuple[Path, Path]:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Agnostic</title>")
    (web / "assets" / "app-1234.js").write_text("console.log(1)")
    (web / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the web root")
    docs = tmp_path / "guides"
    (docs / "admin").mkdir(parents=True)
    (docs / "admin" / "install.md").write_text("# Install Agnostic\n\nSteps.")
    (docs / "operator.md").write_text("# Operator guide\n")
    (docs / "notes.txt").write_text("not a guide")
    return web, docs


def client_certificate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agnostic-control-plane")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return cert.public_bytes(serialization.Encoding.PEM).decode(), key_pem


async def test_security_headers_on_every_response(stack: Stack) -> None:
    response = await stack.client().get("/healthz")
    csp = response.headers["content-security-policy"]
    assert csp == content_security_policy()
    assert "require-trusted-types-for 'script'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in response.headers  # public URL is plain http in tests

    docs = await stack.client().get("/api/v1/docs")
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]


async def test_hsts_and_report_only(sqlite_database: str) -> None:
    async with running_stack(
        sqlite_database, http={"public_url": "https://agnostic.corp", "csp_report_only": True}
    ) as stack:
        response = await stack.client().get("/healthz")
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert "content-security-policy" not in response.headers
    assert "content-security-policy-report-only" in response.headers


async def test_metrics_stay_off_the_main_port_without_a_token(stack: Stack) -> None:
    # Served on the metrics port of their own; the ingress routes the main port.
    assert (await stack.client().get("/metrics")).status_code == 404


async def test_metrics_endpoint(sqlite_database: str) -> None:
    async with running_stack(sqlite_database, metrics={"token": "scrape-me"}) as stack:
        client = stack.client()
        client.headers["Authorization"] = "Bearer scrape-me"
        _ = await client.get("/healthz")
        body = (await client.get("/metrics")).text
    assert 'agnostic_http_requests_total{method="GET",route="/healthz",status="200"}' in body
    assert "agnostic_build_info" in body
    assert "agnostic_http_request_duration_seconds_bucket" in body


async def test_metrics_token(sqlite_database: str) -> None:
    async with running_stack(sqlite_database, metrics={"token": "scrape-me"}) as stack:
        client = stack.client()
        assert (await client.get("/metrics")).status_code == 401
        allowed = await client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert allowed.status_code == 200


async def test_web_app_and_guides(sqlite_database: str, site: tuple[Path, Path]) -> None:
    web, docs = site
    async with running_stack(sqlite_database, http={"web_dir": str(web), "docs_dir": str(docs)}) as stack:
        client = stack.client()
        page = await client.get("/i/prod/chat")
        asset = await client.get("/assets/app-1234.js")
        favicon = await client.get("/favicon.svg")
        missing_asset = await client.get("/assets/gone.js")
        escape = await client.get("/..%2f..%2fsecret.txt")
        api_404 = await client.get("/api/v1/does-not-exist")
        health = await client.get("/healthz")
        info = (await client.get("/api/v1/system/info")).json()
        index = (await client.get("/api/v1/system/docs")).json()
        guide = await client.get("/api/v1/system/docs/admin/install.md")
        not_markdown = await client.get("/api/v1/system/docs/notes.txt")
        traversal = await client.get("/api/v1/system/docs/..%2fweb%2findex.html")

    assert page.status_code == 200
    assert "<title>Agnostic</title>" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert "content-security-policy" in page.headers
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert favicon.text == "<svg/>"
    assert missing_asset.status_code == 404
    assert "outside the web root" not in escape.text
    assert api_404.status_code == 404
    assert api_404.headers["content-type"].startswith("application/")
    assert health.json()["status"] == "ok"

    assert info["docs_available"] is True
    assert info["web_app"] is True
    assert [entry["path"] for entry in index["guides"]] == ["admin/install.md", "operator.md"]
    assert index["guides"][0]["title"] == "Install Agnostic"
    assert guide.text.startswith("# Install Agnostic")
    assert guide.headers["content-type"].startswith("text/markdown")
    assert not_markdown.status_code == 404
    assert traversal.status_code == 404


async def test_client_certificate_for_a_runtime(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    cert_pem, key_pem = client_certificate()

    mismatched = await owner.post(
        "/api/v1/instances/probe",
        json={"endpoint_url": "http://prod.agentos.test:7777", "client_cert_pem": cert_pem},
    )
    assert mismatched.status_code == 422
    assert "both" in mismatched.json()["detail"]

    instance = await connect(owner, fake, client_cert_pem=cert_pem, client_key_pem=key_pem)
    assert instance["has_client_certificate"] is True
    assert "client_key_pem" not in instance

    async with stack.container() as request:
        box = await request.get(SecretBox)
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    from agnostic_instances.infrastructure.tables import InstanceRow  # noqa: PLC0415

    async with stack.container() as request:
        session = await request.get(AsyncSession)
        sealed = await session.scalar(select(InstanceRow.client_key_enc).where(InstanceRow.id == instance["id"]))
    assert sealed is not None
    assert key_pem not in sealed
    assert box.open(sealed).decode() == key_pem

    garbage = await owner.patch(
        f"/api/v1/instances/{instance['id']}", json={"client_cert_pem": "nope", "client_key_pem": "nope"}
    )
    assert garbage.status_code == 422

    removed = await owner.patch(
        f"/api/v1/instances/{instance['id']}", json={"client_cert_pem": "", "client_key_pem": ""}
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["has_client_certificate"] is False
    events = (await owner.get("/api/v1/audit/events", params={"action": "instances.update"})).json()
    assert any("client_certificate" in (event.get("diff") or {}) for event in events["data"])


async def test_direct_mode_token_and_csp(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    assert instance["network_mode"] == "gateway"

    off = await owner.post(f"/api/v1/instances/{instance['slug']}/token")
    assert off.status_code == 409
    assert off.json()["code"] == "direct_mode_off"

    switched = await owner.patch(
        f"/api/v1/instances/{instance['id']}",
        json={"network_mode": "direct", "browser_url": "https://agentos.northwind.example"},
    )
    assert switched.status_code == 200, switched.text
    assert (switched.json()["network_mode"], switched.json()["browser_url"]) == (
        "direct",
        "https://agentos.northwind.example",
    )

    issued = await owner.post(f"/api/v1/instances/{instance['slug']}/token")
    assert issued.status_code == 200, issued.text
    assert issued.headers["cache-control"] == "no-store"
    body = issued.json()
    assert body["base_url"] == "https://agentos.northwind.example"
    claims = jwt.decode(body["token"], options={"verify_signature": False})
    assert claims["agnostic"]["via"] == "direct"
    assert claims["scopes"] == ["agent_os:admin"]
    again = (await owner.post(f"/api/v1/instances/{instance['slug']}/token")).json()
    assert again["token"] == body["token"]  # cached until shortly before it expires

    csp = (await owner.get("/healthz")).headers["content-security-policy"]
    assert "connect-src 'self' https://agentos.northwind.example" in csp

    events = (await owner.get("/api/v1/audit/events", params={"action": "gateway.direct_token"})).json()["data"]
    assert len(events) == 1


async def test_direct_mode_needs_https_in_production(sqlite_database: str) -> None:
    master_key = encode_local_key(bytes(range(32)))
    async with running_stack(sqlite_database, env="production", secrets={"master_key": master_key}) as stack:
        owner = await stack.owner()
        fake = stack.runtime("prod.agentos.test")
        instance = await connect(owner, fake)
        refused = await owner.patch(f"/api/v1/instances/{instance['id']}", json={"network_mode": "direct"})
    assert refused.status_code == 422
    assert "https" in refused.json()["detail"]
