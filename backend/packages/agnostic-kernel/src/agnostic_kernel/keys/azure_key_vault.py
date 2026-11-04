"""Azure Key Vault (or Managed HSM): ``wrapkey`` / ``unwrapkey`` with an RSA key, over the Key Vault REST API.

Credentials, in order: a client secret, a workload-identity federated token (``federated_token_file``, or
``AZURE_FEDERATED_TOKEN_FILE`` as AKS sets it), or the managed identity of the VM/pod (IMDS). Tenant and client id
fall back to ``AZURE_TENANT_ID`` / ``AZURE_CLIENT_ID``. The wrapped value records the key version
(``<version>:<value>``), so wrapping with a newer version keeps older wraps readable.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlsplit

import httpx

from agnostic_kernel.keys import KeyProviderError, env, send
from agnostic_kernel.settings import AzureKeyVaultSettings

API_VERSION = "7.4"
IMDS_URL = "http://169.254.169.254/metadata/identity/oauth2/token"
CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class AzureKeyVaultProvider:
    name = "azure-key-vault"

    def __init__(self, settings: AzureKeyVaultSettings, client: httpx.AsyncClient) -> None:
        if not settings.vault_url or not settings.key_name:
            raise KeyProviderError(
                "AGNOSTIC_SECRETS__AZURE__VAULT_URL and __KEY_NAME are required for the azure-key-vault provider"
            )
        self._settings = settings
        self._vault = settings.vault_url.rstrip("/")
        host = urlsplit(self._vault).hostname or ""
        resource = (
            "https://managedhsm.azure.net" if host.endswith(".managedhsm.azure.net") else "https://vault.azure.net"
        )
        self._resource = resource
        self._client = client
        self._token: str | None = None

    async def _access_token(self) -> str:
        if self._token is not None:
            return self._token
        settings = self._settings
        tenant = settings.tenant_id or env("AZURE_TENANT_ID")
        client_id = settings.client_id or env("AZURE_CLIENT_ID")
        federated = settings.federated_token_file or (
            Path(value) if (value := env("AZURE_FEDERATED_TOKEN_FILE")) else None
        )
        secret = settings.client_secret.get_secret_value() if settings.client_secret is not None else None
        secret = secret or env("AZURE_CLIENT_SECRET")
        if settings.managed_identity or not (tenant and client_id and (secret or federated)):
            if not settings.managed_identity:
                raise KeyProviderError(
                    "no Azure credentials: set tenant and client id with a client secret or a federated token file, "
                    "or AGNOSTIC_SECRETS__AZURE__MANAGED_IDENTITY=true"
                )
            self._token = await self._managed_identity_token(client_id)
            return self._token
        form = {"grant_type": "client_credentials", "client_id": client_id, "scope": f"{self._resource}/.default"}
        if secret:
            form["client_secret"] = secret
        else:
            assert federated is not None
            form["client_assertion_type"] = CLIENT_ASSERTION_TYPE
            form["client_assertion"] = federated.read_text(encoding="utf-8").strip()
        authority = (env("AZURE_AUTHORITY_HOST") or settings.authority_host).rstrip("/")
        request = self._client.build_request("POST", f"{authority}/{tenant}/oauth2/v2.0/token", data=form)
        response = await send(self._client, request, "Microsoft Entra token request")
        token = response.json().get("access_token")
        if not isinstance(token, str):
            raise KeyProviderError("Microsoft Entra returned no access token")
        self._token = token
        return token

    async def _managed_identity_token(self, client_id: str | None) -> str:
        params = {"api-version": "2018-02-01", "resource": self._resource}
        if client_id:
            params["client_id"] = client_id
        request = self._client.build_request("GET", IMDS_URL, params=params, headers={"Metadata": "true"})
        response = await send(self._client, request, "managed identity token request")
        token = response.json().get("access_token")
        if not isinstance(token, str):
            raise KeyProviderError("the managed identity endpoint returned no access token")
        return token

    async def _key_operation(self, operation: str, version: str, value: str) -> dict[str, Any]:
        name = quote(self._settings.key_name or "", safe="")
        path = f"{self._vault}/keys/{name}" + (f"/{quote(version, safe='')}" if version else "") + f"/{operation}"
        request = self._client.build_request(
            "POST",
            path,
            params={"api-version": API_VERSION},
            json={"alg": self._settings.algorithm, "value": value},
            headers={"Authorization": f"Bearer {await self._access_token()}"},
        )
        response = await send(self._client, request, f"Azure Key Vault {operation}")
        return cast("dict[str, Any]", response.json())

    async def wrap(self, key: bytes) -> str:
        data = await self._key_operation("wrapkey", self._settings.key_version or "", _b64url(key))
        value, kid = data.get("value"), data.get("kid")
        if not isinstance(value, str) or not isinstance(kid, str):
            raise KeyProviderError("Azure Key Vault wrapkey returned no wrapped key")
        return f"{kid.rstrip('/').rsplit('/', 1)[-1]}:{value}"

    async def unwrap(self, wrapped: str) -> bytes:
        version, _, value = wrapped.partition(":")
        if not value:
            raise KeyProviderError("the master key isn't an Azure Key Vault wrapped key (<key version>:<value>)")
        data = await self._key_operation("unwrapkey", version, value)
        plaintext = data.get("value")
        if not isinstance(plaintext, str):
            raise KeyProviderError("Azure Key Vault unwrapkey returned no key")
        return _b64url_decode(plaintext)

    def describe(self) -> Mapping[str, str]:
        return {
            "provider": self.name,
            "vault": self._vault,
            "key": self._settings.key_name or "",
            "algorithm": self._settings.algorithm,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
