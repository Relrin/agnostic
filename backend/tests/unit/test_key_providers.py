"""Master-key providers against fake KMS endpoints, the key ring, and re-sealing stored secrets."""

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from agnostic_kernel.crypto import SecretBox, SecretDecryptionError, SecretsConfigError, encode_local_key, key_id
from agnostic_kernel.db import create_engine
from agnostic_kernel.keys import WRAP_CONTEXT, KeyProviderError, create_key_provider, load_secret_box
from agnostic_kernel.modules import SealedColumn
from agnostic_kernel.rewrap import scan
from agnostic_kernel.settings import (
    AwsKmsSettings,
    AzureKeyVaultSettings,
    DatabaseSettings,
    GcpKmsSettings,
    SecretsSettings,
    VaultKeySettings,
)

KEY = bytes(range(32))
OTHER = bytes(range(32, 64))

type Handler = Callable[[httpx.Request], httpx.Response]


class FakeKms:
    """Wraps by XOR-ing with a fixed pad and records every request; enough to check what providers send."""

    def __init__(self, handler: Callable[[FakeKms, httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._handler(self, request)

        return httpx.MockTransport(handle)

    @staticmethod
    def seal(data: bytes) -> bytes:
        return bytes(b ^ 0x5A for b in data)


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content or b"{}")


def _vault(_: FakeKms, request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/auth/kubernetes/login":
        assert _body(request) == {"role": "agnostic", "jwt": "k8s-jwt"}
        return httpx.Response(200, json={"auth": {"client_token": "hvs.k8s"}})
    assert request.headers["X-Vault-Token"] in {"hvs.static", "hvs.k8s"}
    assert request.headers["X-Vault-Namespace"] == "platform"
    body = _body(request)
    if request.url.path == "/v1/transit/encrypt/agnostic":
        sealed = FakeKms.seal(base64.b64decode(body["plaintext"]))
        return httpx.Response(200, json={"data": {"ciphertext": "vault:v1:" + base64.b64encode(sealed).decode()}})
    if request.url.path == "/v1/transit/decrypt/agnostic":
        sealed = base64.b64decode(body["ciphertext"].removeprefix("vault:v1:"))
        return httpx.Response(200, json={"data": {"plaintext": base64.b64encode(FakeKms.seal(sealed)).decode()}})
    return httpx.Response(404, json={"errors": ["no handler"]})


async def test_vault_transit_round_trip_with_token() -> None:
    kms = FakeKms(_vault)
    settings = SecretsSettings(
        provider="vault",
        vault=VaultKeySettings(address="https://vault.corp:8200", namespace="platform", token="hvs.static"),  # pyright: ignore[reportArgumentType]
    )
    provider = create_key_provider(settings, transport=kms.transport())
    wrapped = await provider.wrap(KEY)
    assert wrapped.startswith("vault:v1:")
    assert await provider.unwrap(wrapped) == KEY
    assert provider.describe()["key"] == "transit/agnostic"
    await provider.aclose()


async def test_vault_kubernetes_login(tmp_path: Path) -> None:
    jwt_file = tmp_path / "token"
    jwt_file.write_text("k8s-jwt\n")
    kms = FakeKms(_vault)
    settings = VaultKeySettings(
        address="https://vault.corp",
        namespace="platform",
        auth="kubernetes",
        role="agnostic",
        kubernetes_token_file=jwt_file,
    )
    secrets = SecretsSettings(provider="vault", vault=settings)
    provider = create_key_provider(secrets, transport=kms.transport())
    assert await provider.unwrap(await provider.wrap(KEY)) == KEY
    assert sum(r.url.path.endswith("/login") for r in kms.requests) == 1  # the token is reused


async def test_vault_errors_are_key_provider_errors() -> None:
    kms = FakeKms(lambda _, __: httpx.Response(403, json={"errors": ["permission denied"]}))
    secrets = SecretsSettings(provider="vault", vault=VaultKeySettings(address="https://v", token="t"))  # pyright: ignore[reportArgumentType]
    provider = create_key_provider(secrets, transport=kms.transport())
    with pytest.raises(KeyProviderError, match="permission denied"):
        await provider.unwrap("vault:v1:AAAA")
    with pytest.raises(KeyProviderError, match="isn't Vault transit ciphertext"):
        await provider.unwrap("not-vault")


def _aws(_: FakeKms, request: httpx.Request) -> httpx.Response:
    if request.url.host.startswith("sts."):
        form = dict(httpx.QueryParams(request.content.decode()))
        assert form["Action"] == "AssumeRoleWithWebIdentity"
        assert form["WebIdentityToken"] == "irsa-token"
        return httpx.Response(
            200,
            text=(
                "<AssumeRoleWithWebIdentityResponse><Credentials><AccessKeyId>ASIATEMP</AccessKeyId>"
                "<SecretAccessKey>temp-secret</SecretAccessKey><SessionToken>session</SessionToken>"
                "</Credentials></AssumeRoleWithWebIdentityResponse>"
            ),
        )
    authorization = request.headers["authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=")
    assert "/eu-west-1/kms/aws4_request" in authorization
    body = _body(request)
    assert body["EncryptionContext"] == {"purpose": WRAP_CONTEXT}
    match request.headers["x-amz-target"]:
        case "TrentService.Encrypt":
            blob = FakeKms.seal(base64.b64decode(body["Plaintext"]))
            return httpx.Response(200, json={"CiphertextBlob": base64.b64encode(blob).decode()})
        case "TrentService.Decrypt":
            plain = FakeKms.seal(base64.b64decode(body["CiphertextBlob"]))
            return httpx.Response(200, json={"Plaintext": base64.b64encode(plain).decode()})
        case _:
            return httpx.Response(400, json={"__type": "UnknownOperationException"})


async def test_aws_kms_static_credentials() -> None:
    kms = FakeKms(_aws)
    settings = AwsKmsSettings(
        key_id="arn:aws:kms:eu-west-1:111122223333:key/abcd",
        access_key_id="AKIA",
        secret_access_key="secret",  # pyright: ignore[reportArgumentType]
    )
    provider = create_key_provider(SecretsSettings(provider="aws-kms", aws=settings), transport=kms.transport())
    assert await provider.unwrap(await provider.wrap(KEY)) == KEY
    assert provider.describe()["region"] == "eu-west-1"  # taken from the key ARN
    assert kms.requests[0].url.host == "kms.eu-west-1.amazonaws.com"


async def test_aws_kms_web_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    token = tmp_path / "irsa"
    token.write_text("irsa-token")
    kms = FakeKms(_aws)
    settings = AwsKmsSettings(
        key_id="alias/agnostic",
        region="eu-west-1",
        role_arn="arn:aws:iam::1:role/agnostic",
        web_identity_token_file=token,
    )
    provider = create_key_provider(SecretsSettings(provider="aws-kms", aws=settings), transport=kms.transport())
    assert await provider.unwrap(await provider.wrap(KEY)) == KEY
    signed = kms.requests[-1]
    assert signed.headers["x-amz-security-token"] == "session"
    assert "Credential=ASIATEMP/" in signed.headers["authorization"]


def _azure(_: FakeKms, request: httpx.Request) -> httpx.Response:
    if request.url.host == "login.microsoftonline.com":
        form = dict(httpx.QueryParams(request.content.decode()))
        assert form["scope"] == "https://vault.azure.net/.default"
        assert form["client_secret"] == "s3cret"
        return httpx.Response(200, json={"access_token": "entra-token"})
    assert request.headers["authorization"] == "Bearer entra-token"
    body = _body(request)
    assert body["alg"] == "RSA-OAEP-256"
    raw = base64.urlsafe_b64decode(body["value"] + "==")
    value = base64.urlsafe_b64encode(FakeKms.seal(raw)).decode().rstrip("=")
    if request.url.path.endswith("/wrapkey"):
        return httpx.Response(200, json={"kid": "https://corp.vault.azure.net/keys/agnostic/v7", "value": value})
    assert request.url.path == "/keys/agnostic/v7/unwrapkey"
    return httpx.Response(200, json={"value": value})


async def test_azure_key_vault_records_the_key_version() -> None:
    kms = FakeKms(_azure)
    settings = AzureKeyVaultSettings(
        vault_url="https://corp.vault.azure.net",
        key_name="agnostic",
        tenant_id="t",
        client_id="c",
        client_secret="s3cret",  # pyright: ignore[reportArgumentType]
    )
    provider = create_key_provider(
        SecretsSettings(provider="azure-key-vault", azure=settings), transport=kms.transport()
    )
    wrapped = await provider.wrap(KEY)
    assert wrapped.startswith("v7:")
    assert await provider.unwrap(wrapped) == KEY


def _gcp(_: FakeKms, request: httpx.Request) -> httpx.Response:
    if request.url.host == "oauth2.googleapis.com":
        form = dict(httpx.QueryParams(request.content.decode()))
        assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
        assert form["assertion"].count(".") == 2
        return httpx.Response(200, json={"access_token": "ya29.token"})
    assert request.headers["authorization"] == "Bearer ya29.token"
    body = _body(request)
    assert base64.b64decode(body["additionalAuthenticatedData"]).decode() == WRAP_CONTEXT
    if request.url.path.endswith(":encrypt"):
        blob = FakeKms.seal(base64.b64decode(body["plaintext"]))
        return httpx.Response(200, json={"ciphertext": base64.b64encode(blob).decode()})
    plain = FakeKms.seal(base64.b64decode(body["ciphertext"]))
    return httpx.Response(200, json={"plaintext": base64.b64encode(plain).decode()})


async def test_gcp_kms_service_account(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    credentials = tmp_path / "sa.json"
    credentials.write_text(
        json.dumps({"type": "service_account", "client_email": "kms@p.iam", "private_key": pem.decode()})
    )
    kms = FakeKms(_gcp)
    settings = GcpKmsSettings(
        key_name="projects/p/locations/global/keyRings/r/cryptoKeys/agnostic", credentials_file=credentials
    )
    provider = create_key_provider(SecretsSettings(provider="gcp-kms", gcp=settings), transport=kms.transport())
    assert await provider.unwrap(await provider.wrap(KEY)) == KEY
    assert kms.requests[1].url.path == "/v1/projects/p/locations/global/keyRings/r/cryptoKeys/agnostic:encrypt"


def test_providers_refuse_incomplete_settings() -> None:
    with pytest.raises(KeyProviderError, match="KEY_ID"):
        create_key_provider(SecretsSettings(provider="aws-kms"))
    with pytest.raises(KeyProviderError, match="VAULT_URL"):
        create_key_provider(SecretsSettings(provider="azure-key-vault"))
    with pytest.raises(KeyProviderError, match="KEY_NAME"):
        create_key_provider(SecretsSettings(provider="gcp-kms"))


async def test_load_secret_box_through_a_kms_with_a_previous_key() -> None:
    kms = FakeKms(_vault)
    vault = VaultKeySettings(address="https://v", namespace="platform", token="hvs.static")  # pyright: ignore[reportArgumentType]
    provider = create_key_provider(SecretsSettings(provider="vault", vault=vault), transport=kms.transport())
    current, previous = await provider.wrap(KEY), await provider.wrap(OTHER)
    settings = SecretsSettings(provider="vault", vault=vault, master_key=current, previous_keys=[previous])  # pyright: ignore[reportArgumentType]
    box = await load_secret_box(settings, environment="production", transport=kms.transport())
    assert box.key_ids == (key_id(KEY), key_id(OTHER))
    with pytest.raises(SecretsConfigError, match="wrapped by vault"):
        await load_secret_box(SecretsSettings(provider="vault", vault=vault), environment="development")


async def test_load_secret_box_local_previous_keys_file(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    previous.write_text(f"# retired 2026-10\n{encode_local_key(OTHER)}\n")
    settings = SecretsSettings(master_key=encode_local_key(KEY), previous_keys_file=previous)  # pyright: ignore[reportArgumentType]
    box = await load_secret_box(settings, environment="production")
    assert box.key_ids == (key_id(KEY), key_id(OTHER))


def test_key_ring_opens_old_values_and_reseals() -> None:
    old = SecretBox(OTHER)
    sealed = old.seal(b"secret")
    rotated = SecretBox(KEY, [OTHER])
    assert rotated.open(sealed) == b"secret"
    resealed = rotated.reseal(sealed)
    assert resealed is not None
    assert rotated.sealed_with(resealed) == rotated.key_id
    assert rotated.reseal(resealed) is None
    with pytest.raises(SecretDecryptionError, match="isn't configured"):
        SecretBox(KEY).open(sealed)
    assert rotated.derive_all(b"ctx")[0] == rotated.derive(b"ctx") == SecretBox(KEY).derive(b"ctx")
    assert rotated.derive_all(b"ctx")[1] == old.derive(b"ctx")


async def test_scan_and_reseal_columns(sqlite_database: str) -> None:
    engine = create_engine(DatabaseSettings(url=sqlite_database))  # pyright: ignore[reportArgumentType]
    old, new = SecretBox(OTHER), SecretBox(KEY, [OTHER])
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE plain_secrets (id TEXT PRIMARY KEY, value_enc TEXT)"))
        await connection.execute(text("CREATE TABLE json_secrets (id TEXT PRIMARY KEY, config JSON)"))
        await connection.execute(
            text("INSERT INTO plain_secrets VALUES ('a', :a), ('b', :b), ('c', NULL), ('d', '$argon2id$hash')"),
            {"a": old.seal(b"one"), "b": new.seal(b"two")},
        )
        await connection.execute(
            text("INSERT INTO json_secrets VALUES ('x', :config)"),
            {"config": json.dumps({"client_secret": old.seal(b"three"), "client_id": "kept"})},
        )
    columns = [
        SealedColumn("plain_secrets", "value_enc"),
        SealedColumn("json_secrets", "config", json_keys=("client_secret",)),
        SealedColumn("not_created_yet", "value_enc"),
    ]
    try:
        before = await scan(engine, new, columns)
        assert before[0].by_key == {old.key_id: 1, new.key_id: 1}
        assert before[1].by_key == {old.key_id: 1}
        assert before[2].missing_table

        rotated = await scan(engine, new, columns, reseal=True)
        assert [report.resealed for report in rotated[:2]] == [1, 1]

        after = await scan(engine, SecretBox(KEY), columns)
        assert after[0].by_key == {new.key_id: 2}
        assert after[1].by_key == {new.key_id: 1}
        async with engine.connect() as connection:
            config = json.loads((await connection.execute(text("SELECT config FROM json_secrets"))).scalar_one())
            hashed = (await connection.execute(text("SELECT value_enc FROM plain_secrets WHERE id = 'd'"))).scalar_one()
        assert config["client_id"] == "kept"
        assert SecretBox(KEY).open(config["client_secret"]) == b"three"
        assert hashed == "$argon2id$hash"
    finally:
        await engine.dispose()
