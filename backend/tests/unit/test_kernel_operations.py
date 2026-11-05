"""Operating the control plane: job administration and recovery, the worker loop, metrics, outbound TLS, KMS auth."""

import asyncio
import json
import ssl
from pathlib import Path
from typing import Any

import httpx
import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector

from agnostic_kernel import metrics
from agnostic_kernel.db import create_engine
from agnostic_kernel.job_admin import JobAdmin, refresh_job_metrics
from agnostic_kernel.jobs import keep_working, register_jobs, retry_stalled_jobs
from agnostic_kernel.keys import KeyProviderError, create_key_provider
from agnostic_kernel.modules import JobSpec
from agnostic_kernel.settings import (
    AzureKeyVaultSettings,
    DatabaseSettings,
    GcpKmsSettings,
    MetricsSettings,
    OutboundTlsSettings,
    SecretsSettings,
    VaultKeySettings,
)
from agnostic_kernel.tls import outbound_ssl_context


async def noop(context: procrastinate.JobContext, **_: Any) -> None:
    del context


@pytest.fixture
def jobs_app() -> procrastinate.App:
    app = procrastinate.App(connector=InMemoryConnector())
    register_jobs(app, [JobSpec(name="test.noop", func=noop, queue="default"), JobSpec("test.other", noop, "slow")])
    return app


async def test_job_admin_on_the_in_memory_queue(jobs_app: procrastinate.App, sqlite_database: str) -> None:
    engine = create_engine(DatabaseSettings(url=sqlite_database))  # pyright: ignore[reportArgumentType]
    try:
        async with jobs_app.open_async():
            first = await jobs_app.configure_task("test.noop").defer_async(item="a")
            await jobs_app.configure_task("test.other").defer_async()
            connector = jobs_app.connector
            assert isinstance(connector, InMemoryConnector)
            connector.jobs[first]["status"] = "failed"
            admin = JobAdmin(jobs_app, engine)

            queues = {stats.queue: stats for stats in await admin.queues()}
            assert (queues["default"].failed, queues["slow"].waiting) == (1, 1)
            assert queues["default"].oldest_wait_seconds is None  # lag needs PostgreSQL's event table

            failed = await admin.failed()
            assert [(job.id, job.argument_names) for job in failed] == [(first, ("item",))]
            assert await admin.failed(before=first) == []
            assert await admin.discard(first) is False  # discarding needs PostgreSQL

            await refresh_job_metrics(admin)
            assert metrics.REGISTRY.get_sample_value("agnostic_jobs_failed", {"queue": "default"}) == 1

            await admin.retry(first)
            assert connector.jobs[first]["status"] == "todo"
    finally:
        await engine.dispose()


class StalledManager:
    def __init__(self, stalled: list[str]) -> None:
        self.stalled = stalled
        self.retried: list[str] = []

    async def get_stalled_jobs(self, seconds_since_heartbeat: float) -> list[Any]:
        assert seconds_since_heartbeat == 60.0
        return [
            type("Job", (), {"id": index, "task_name": name, "worker_id": 7})()
            for index, name in enumerate(self.stalled)
        ]

    async def retry_job(self, job: Any) -> None:
        self.retried.append(job.task_name)


async def test_retry_stalled_jobs_queues_abandoned_jobs_again() -> None:
    manager = StalledManager(["audit.deliver", "sources.sync"])
    context = type("Context", (), {"app": type("App", (), {"job_manager": manager})()})()
    assert await retry_stalled_jobs(context, timestamp=0) == 2  # pyright: ignore[reportArgumentType]
    assert manager.retried == ["audit.deliver", "sources.sync"]


async def test_keep_working_restarts_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[str] = []

    class FlakyApp:
        async def run_worker_async(self, **_: Any) -> None:
            runs.append("run")
            if len(runs) == 1:
                return  # what Procrastinate does after losing its listener
            if len(runs) == 2:
                raise OSError("database is gone")
            await asyncio.Event().wait()  # healthy: runs until cancelled
            return

    real_sleep = asyncio.sleep

    async def no_backoff(_: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr("agnostic_kernel.jobs.asyncio.sleep", no_backoff)
    task = asyncio.create_task(keep_working(FlakyApp(), {}))  # pyright: ignore[reportArgumentType]
    for _ in range(50):
        await real_sleep(0)
        if len(runs) == 3:
            break
    assert len(runs) == 3
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_refreshing_keeps_going_after_a_failed_refresh() -> None:
    calls = 0

    async def refresh() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database down")

    async with metrics.refreshing(refresh, every=0.01):
        for _ in range(100):
            await asyncio.sleep(0.01)
            if calls >= 2:
                break
    assert calls >= 2


def test_serve_metrics_does_nothing_when_disabled() -> None:
    metrics.serve_metrics(MetricsSettings(enabled=False))


def test_outbound_context_trusts_extra_cas_and_can_skip_verification(tmp_path: Path) -> None:
    unverified = outbound_ssl_context(OutboundTlsSettings(), verify=False)
    assert unverified.verify_mode == ssl.CERT_NONE
    assert unverified.check_hostname is False
    with pytest.raises(ssl.SSLError):
        outbound_ssl_context(OutboundTlsSettings(), extra_ca_pem="not a certificate")
    missing = tmp_path / "missing.pem"
    with pytest.raises(OSError):
        outbound_ssl_context(OutboundTlsSettings(ca_file=missing))


async def test_vault_approle_login_and_secret_file(tmp_path: Path) -> None:
    secret = tmp_path / "secret-id"
    secret.write_text("s3cret\n")
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen.append({"path": request.url.path, "body": body, "token": request.headers.get("X-Vault-Token")})
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json={"auth": {"client_token": "hvs.approle"}})
        return httpx.Response(200, json={"data": {"ciphertext": "vault:v2:abc"}})

    settings = VaultKeySettings(address="https://vault", auth="approle", role_id="agnostic", secret_id_file=secret)
    provider = create_key_provider(
        SecretsSettings(provider="vault", vault=settings), transport=httpx.MockTransport(handle)
    )
    assert await provider.wrap(b"k" * 32) == "vault:v2:abc"
    assert seen[0]["body"] == {"role_id": "agnostic", "secret_id": "s3cret"}
    assert seen[1]["token"] == "hvs.approle"


async def test_vault_requires_an_address_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    with pytest.raises(KeyProviderError, match="ADDRESS"):
        create_key_provider(SecretsSettings(provider="vault"))
    provider = create_key_provider(
        SecretsSettings(provider="vault", vault=VaultKeySettings(address="https://vault")),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    with pytest.raises(KeyProviderError, match="VAULT_TOKEN"):
        await provider.wrap(b"k" * 32)


async def test_azure_managed_identity_and_managed_hsm(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_FEDERATED_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "169.254.169.254":
            assert request.headers["Metadata"] == "true"
            assert request.url.params["resource"] == "https://managedhsm.azure.net"
            return httpx.Response(200, json={"access_token": "mi-token"})
        assert request.headers["authorization"] == "Bearer mi-token"
        return httpx.Response(403, json={"error": {"message": "Operation wrapKey is not permitted"}})

    settings = AzureKeyVaultSettings(vault_url="https://corp.managedhsm.azure.net", key_name="k", managed_identity=True)
    provider = create_key_provider(
        SecretsSettings(provider="azure-key-vault", azure=settings), transport=httpx.MockTransport(handle)
    )
    with pytest.raises(KeyProviderError, match="not permitted"):
        await provider.wrap(b"k" * 32)
    with pytest.raises(KeyProviderError, match="key version"):
        await provider.unwrap("no-version-separator")


async def test_azure_needs_some_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_FEDERATED_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)

    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request is expected without credentials, got {request.url}")

    settings = AzureKeyVaultSettings(vault_url="https://corp.vault.azure.net", key_name="k")
    provider = create_key_provider(
        SecretsSettings(provider="azure-key-vault", azure=settings), transport=httpx.MockTransport(handle)
    )
    with pytest.raises(KeyProviderError, match="no Azure credentials"):
        await provider.wrap(b"k" * 32)


async def test_gcp_metadata_server_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "metadata.google.internal":
            assert request.headers["Metadata-Flavor"] == "Google"
            return httpx.Response(200, json={"access_token": "gke-token"})
        return httpx.Response(200, json={"plaintext": "a2V5"})

    settings = GcpKmsSettings(key_name="projects/p/locations/l/keyRings/r/cryptoKeys/k")
    provider = create_key_provider(
        SecretsSettings(provider="gcp-kms", gcp=settings), transport=httpx.MockTransport(handle)
    )
    assert await provider.unwrap("ciphertext") == b"key"
    assert provider.describe()["key"] == "projects/p/locations/l/keyRings/r/cryptoKeys/k"
