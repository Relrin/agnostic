"""HashiCorp Vault (or OpenBao) Transit: ``encrypt`` / ``decrypt`` with a named key that never leaves Vault.

Authentication: a token (``token``, ``token_file`` or ``VAULT_TOKEN``), Kubernetes service-account login, or
AppRole. The wrapped master key is Vault's own ciphertext (``vault:v<version>:…``), so Transit key rotation keeps
old wraps readable and ``agnostic secrets wrap-key`` re-wraps with the newest version.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import quote

import httpx

from agnostic_kernel.keys import KeyProviderError, env, send
from agnostic_kernel.settings import VaultKeySettings


class VaultTransitProvider:
    name = "vault"

    def __init__(self, settings: VaultKeySettings, client: httpx.AsyncClient) -> None:
        address = settings.address or env("VAULT_ADDR")
        if not address:
            raise KeyProviderError(
                "AGNOSTIC_SECRETS__VAULT__ADDRESS (or VAULT_ADDR) is required for the vault provider"
            )
        self._address = address.rstrip("/")
        self._settings = settings
        self._client = client
        self._token: str | None = None

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        namespace = self._settings.namespace or env("VAULT_NAMESPACE")
        if namespace:
            headers["X-Vault-Namespace"] = namespace
        if token:
            headers["X-Vault-Token"] = token
        return headers

    async def _login(self, method: str, body: Mapping[str, str]) -> str:
        mount = (self._settings.auth_mount or method).strip("/")
        request = self._client.build_request(
            "POST", f"{self._address}/v1/auth/{mount}/login", json=dict(body), headers=self._headers()
        )
        response = await send(self._client, request, f"Vault {method} login")
        auth = cast("dict[str, Any]", response.json().get("auth") or {})
        token = auth.get("client_token")
        if not isinstance(token, str) or not token:
            raise KeyProviderError(f"Vault {method} login returned no client token")
        return token

    async def _vault_token(self) -> str:
        if self._token is not None:
            return self._token
        settings = self._settings
        match settings.auth:
            case "token":
                token = (
                    settings.token.get_secret_value()
                    if settings.token is not None
                    else settings.token_file.read_text(encoding="utf-8").strip()
                    if settings.token_file is not None
                    else env("VAULT_TOKEN")
                )
                if not token:
                    raise KeyProviderError("set AGNOSTIC_SECRETS__VAULT__TOKEN, __TOKEN_FILE or VAULT_TOKEN")
            case "kubernetes":
                if not settings.role:
                    raise KeyProviderError("AGNOSTIC_SECRETS__VAULT__ROLE is required for Kubernetes auth")
                jwt = settings.kubernetes_token_file.read_text(encoding="utf-8").strip()
                token = await self._login("kubernetes", {"role": settings.role, "jwt": jwt})
            case "approle":
                secret_id = (
                    settings.secret_id.get_secret_value()
                    if settings.secret_id is not None
                    else settings.secret_id_file.read_text(encoding="utf-8").strip()
                    if settings.secret_id_file is not None
                    else None
                )
                if not settings.role_id or not secret_id:
                    raise KeyProviderError("AppRole auth needs AGNOSTIC_SECRETS__VAULT__ROLE_ID and __SECRET_ID")
                token = await self._login("approle", {"role_id": settings.role_id, "secret_id": secret_id})
        self._token = token
        return token

    async def _transit(self, operation: str, body: Mapping[str, str]) -> dict[str, Any]:
        mount = self._settings.mount.strip("/")
        url = f"{self._address}/v1/{mount}/{operation}/{quote(self._settings.key_name, safe='')}"
        request = self._client.build_request(
            "POST", url, json=dict(body), headers=self._headers(await self._vault_token())
        )
        response = await send(self._client, request, f"Vault transit {operation}")
        return cast("dict[str, Any]", response.json().get("data") or {})

    async def wrap(self, key: bytes) -> str:
        data = await self._transit("encrypt", {"plaintext": base64.b64encode(key).decode()})
        ciphertext = data.get("ciphertext")
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:"):
            raise KeyProviderError("Vault transit encrypt returned no ciphertext")
        return ciphertext

    async def unwrap(self, wrapped: str) -> bytes:
        if not wrapped.startswith("vault:"):
            raise KeyProviderError("the master key isn't Vault transit ciphertext (vault:v…:…)")
        data = await self._transit("decrypt", {"ciphertext": wrapped})
        plaintext = data.get("plaintext")
        if not isinstance(plaintext, str):
            raise KeyProviderError("Vault transit decrypt returned no plaintext")
        return base64.b64decode(plaintext)

    def describe(self) -> Mapping[str, str]:
        return {
            "provider": self.name,
            "address": self._address,
            "key": f"{self._settings.mount.strip('/')}/{self._settings.key_name}",
            "auth": self._settings.auth,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
