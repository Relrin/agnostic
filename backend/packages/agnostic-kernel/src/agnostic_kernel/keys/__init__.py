"""Master-key providers: where the key-encryption key behind :class:`~agnostic_kernel.crypto.SecretBox` comes from.

The ``local`` provider reads the master key itself from the configuration. The KMS providers (HashiCorp Vault
Transit, AWS KMS, Azure Key Vault, Google Cloud KMS) keep a key that never leaves the KMS; the configuration holds
the master key *wrapped* by it, and every API and worker process unwraps it once when it starts. Sealing and
opening secrets stays local, so a KMS outage only stops processes from starting, never requests in flight.

Every provider talks to its service's REST API through httpx; no vendor SDK is needed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol, cast

import httpx

from agnostic_kernel.crypto import (
    DEVELOPMENT_KEY,
    KEY_BYTES,
    SecretBox,
    SecretsConfigError,
    decode_local_key,
)
from agnostic_kernel.logging import get_logger
from agnostic_kernel.settings import KeyProviderName, OutboundTlsSettings, SecretsSettings, TlsOptions
from agnostic_kernel.tls import endpoint_ssl_context

log = get_logger(__name__)

WRAP_CONTEXT = "agnostic/master-key/v1"
"""Bound to every wrap as additional authenticated data (or encryption context), so a wrapped master key can't be
unwrapped through some other application's use of the same KMS key."""
KMS_TIMEOUT = 15.0


class KeyProviderError(SecretsConfigError):
    """The key provider is unreachable, refused the request, or the wrapped master key doesn't belong to it."""


class KeyProvider(Protocol):
    name: str

    async def wrap(self, key: bytes) -> str:
        """Wrap a 32-byte master key; the text goes into ``AGNOSTIC_SECRETS__MASTER_KEY``."""
        ...

    async def unwrap(self, wrapped: str) -> bytes: ...

    def describe(self) -> Mapping[str, str]:
        """Non-secret facts for ``agnostic config check`` (endpoint, key name)."""
        ...

    async def aclose(self) -> None: ...


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def problem(response: httpx.Response, what: str) -> KeyProviderError:
    """A :class:`KeyProviderError` naming the call and the service's own message when it sent one."""
    detail = ""
    try:
        body: object = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        fields = cast("dict[str, Any]", body)
        for key in ("errors", "error", "message", "Message", "__type", "error_description"):
            value: object = fields.get(key)
            if isinstance(value, dict):
                value = cast("dict[str, Any]", value).get("message")
            if isinstance(value, list):
                value = "; ".join(str(item) for item in cast("list[object]", value))
            if value:
                detail = str(value)
                break
    suffix = f": {detail}" if detail else ""
    return KeyProviderError(f"{what} failed with HTTP {response.status_code}{suffix}")


async def send(client: httpx.AsyncClient, request: httpx.Request, what: str) -> httpx.Response:
    try:
        response = await client.send(request)
    except httpx.HTTPError as exc:
        msg = f"{what} failed: {exc}"
        raise KeyProviderError(msg) from exc
    if response.status_code >= 300:  # noqa: PLR2004
        raise problem(response, what)
    return response


def http_client(
    tls: OutboundTlsSettings, endpoint_tls: TlsOptions, transport: httpx.AsyncBaseTransport | None
) -> httpx.AsyncClient:
    if transport is not None:
        return httpx.AsyncClient(transport=transport, timeout=KMS_TIMEOUT)
    return httpx.AsyncClient(verify=endpoint_ssl_context(tls, endpoint_tls), timeout=KMS_TIMEOUT)


def create_key_provider(
    secrets: SecretsSettings,
    tls: OutboundTlsSettings | None = None,
    *,
    name: KeyProviderName | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> KeyProvider:
    """The configured provider (or ``name``, for ``agnostic secrets wrap-key --to``)."""
    from agnostic_kernel.keys.aws_kms import AwsKmsProvider  # noqa: PLC0415
    from agnostic_kernel.keys.azure_key_vault import AzureKeyVaultProvider  # noqa: PLC0415
    from agnostic_kernel.keys.gcp_kms import GcpKmsProvider  # noqa: PLC0415
    from agnostic_kernel.keys.local import LocalKeyProvider  # noqa: PLC0415
    from agnostic_kernel.keys.vault import VaultTransitProvider  # noqa: PLC0415

    tls = tls or OutboundTlsSettings()
    match name or secrets.provider:
        case "local":
            return LocalKeyProvider()
        case "vault":
            return VaultTransitProvider(secrets.vault, http_client(tls, secrets.vault.tls, transport))
        case "aws-kms":
            return AwsKmsProvider(secrets.aws, http_client(tls, secrets.aws.tls, transport))
        case "azure-key-vault":
            return AzureKeyVaultProvider(secrets.azure, http_client(tls, secrets.azure.tls, transport))
        case "gcp-kms":
            return GcpKmsProvider(secrets.gcp, http_client(tls, secrets.gcp.tls, transport))


def configured_keys(settings: SecretsSettings) -> tuple[str | None, list[str]]:
    """The current master key and the retired ones, as configured (still wrapped for a KMS provider)."""
    current: str | None = None
    if settings.master_key is not None:
        current = settings.master_key.get_secret_value().strip()
    elif settings.master_key_file is not None:
        current = settings.master_key_file.read_text(encoding="utf-8").strip()
    previous = [key.get_secret_value().strip() for key in settings.previous_keys]
    if settings.previous_keys_file is not None:
        lines = settings.previous_keys_file.read_text(encoding="utf-8").splitlines()
        previous.extend(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    return current or None, [key for key in previous if key]


async def unwrap_all(provider: KeyProvider, current: str, previous: list[str]) -> tuple[bytes, list[bytes]]:
    keys = [await provider.unwrap(value) for value in (current, *previous)]
    for key in keys:
        if len(key) != KEY_BYTES:
            msg = f"the {provider.name} provider returned a {len(key)}-byte master key; {KEY_BYTES} bytes are required"
            raise KeyProviderError(msg)
    return keys[0], keys[1:]


async def load_secret_box(
    secrets: SecretsSettings,
    tls: OutboundTlsSettings | None = None,
    *,
    environment: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SecretBox:
    """Build the key ring from the configuration, unwrapping through the configured provider."""
    current, previous = configured_keys(secrets)
    if current is None:
        if environment == "production":
            msg = "AGNOSTIC_SECRETS__MASTER_KEY (or AGNOSTIC_SECRETS__MASTER_KEY_FILE) is required in production"
            raise SecretsConfigError(msg)
        if secrets.provider != "local":
            msg = f"AGNOSTIC_SECRETS__MASTER_KEY must hold the master key wrapped by {secrets.provider}"
            raise SecretsConfigError(msg)
        log.warning("secrets.development_master_key", detail="set AGNOSTIC_SECRETS__MASTER_KEY before real use")
        return SecretBox(DEVELOPMENT_KEY, [decode_local_key(key) for key in previous])
    if secrets.provider == "local":
        return SecretBox(decode_local_key(current), [decode_local_key(key) for key in previous])
    provider = create_key_provider(secrets, tls, transport=transport)
    try:
        key, retired = await unwrap_all(provider, current, previous)
    finally:
        await provider.aclose()
    log.info("secrets.master_key_unwrapped", provider=provider.name, keys=1 + len(retired))
    return SecretBox(key, retired)
