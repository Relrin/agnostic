"""TLS contexts built from real certificate material, and tracing setup."""

import datetime as dt
import ssl
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider

from agnostic_kernel import telemetry
from agnostic_kernel.cache import create_redis
from agnostic_kernel.db import create_engine
from agnostic_kernel.settings import DatabaseSettings, OtelSettings, RedisSettings, TlsOptions
from agnostic_kernel.tls import asyncpg_ssl


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> TlsOptions:
    directory = tmp_path_factory.mktemp("tls")
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agnostic-test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = directory / "cert.pem", directory / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return TlsOptions(ca_file=cert_file, cert_file=cert_file, key_file=key_file)


@pytest.mark.parametrize(
    ("mode", "verify_mode", "check_hostname"),
    [
        ("require", ssl.CERT_NONE, False),
        ("verify-ca", ssl.CERT_REQUIRED, False),
        ("verify-full", ssl.CERT_REQUIRED, True),
    ],
)
def test_asyncpg_contexts_from_material(
    tls_material: TlsOptions, mode: str, verify_mode: ssl.VerifyMode, check_hostname: bool
) -> None:
    context = asyncpg_ssl(mode, tls_material)  # pyright: ignore[reportArgumentType]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == verify_mode
    assert context.check_hostname is check_hostname


async def test_clients_accept_tls_material(tls_material: TlsOptions) -> None:
    engine = create_engine(DatabaseSettings(url="postgresql://u:p@db/cp", sslmode="verify-full", tls=tls_material))  # pyright: ignore[reportArgumentType]
    await engine.dispose()
    redis = create_redis(RedisSettings(url="rediss://cache:6380/0", tls=tls_material))  # pyright: ignore[reportArgumentType]
    await redis.aclose()


def test_tracing_off_without_endpoint() -> None:
    assert telemetry.configure_tracing(OtelSettings()) is None
    telemetry.instrument_app(FastAPI(), None)


async def test_tracing_on_with_endpoint(tls_material: TlsOptions, tmp_path: Path) -> None:
    provider = telemetry.configure_tracing(
        OtelSettings(endpoint="http://127.0.0.1:1/v1/traces", headers={"x-token": "t"}, tls=tls_material)  # pyright: ignore[reportArgumentType]
    )
    assert isinstance(provider, TracerProvider)
    app = FastAPI()
    telemetry.instrument_app(app, provider)
    engine = create_engine(DatabaseSettings(url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}"))  # pyright: ignore[reportArgumentType]
    telemetry.instrument_engine(engine, provider)
    await engine.dispose()
    provider.shutdown()
