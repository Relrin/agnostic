"""Google Cloud KMS: ``encrypt`` / ``decrypt`` with a symmetric crypto key, over the Cloud KMS REST API.

Credentials: a service-account key file (``credentials_file`` or ``GOOGLE_APPLICATION_CREDENTIALS``) signs a JWT
that is exchanged for an access token; without one, the metadata server's token is used (GKE workload identity,
Compute Engine). The token endpoint is fixed, so a key file can't send the signed assertion elsewhere. Every wrap
carries ``agnostic/master-key/v1`` as additional authenticated data.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx
import orjson
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from agnostic_kernel.keys import WRAP_CONTEXT, KeyProviderError, env, send
from agnostic_kernel.settings import GcpKmsSettings

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"  # noqa: S105
SCOPE = "https://www.googleapis.com/auth/cloudkms"
JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ASSERTION_TTL = 3600


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def service_account_assertion(info: Mapping[str, Any], *, now: int) -> str:
    """The RS256 JWT a service account exchanges for a Cloud KMS access token."""
    try:
        key = serialization.load_pem_private_key(str(info["private_key"]).encode(), password=None)
    except (KeyError, ValueError, TypeError) as exc:
        raise KeyProviderError("the service-account key file has no readable private key") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise KeyProviderError("the service-account private key must be an RSA key")
    header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
    if info.get("private_key_id"):
        header["kid"] = str(info["private_key_id"])
    claims = {"iss": info.get("client_email"), "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + ASSERTION_TTL}
    signing_input = f"{_b64url(orjson.dumps(header))}.{_b64url(orjson.dumps(claims))}".encode()
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode()}.{_b64url(signature)}"


class GcpKmsProvider:
    name = "gcp-kms"

    def __init__(self, settings: GcpKmsSettings, client: httpx.AsyncClient) -> None:
        if not settings.key_name or "/cryptoKeys/" not in settings.key_name:
            raise KeyProviderError(
                "AGNOSTIC_SECRETS__GCP__KEY_NAME (projects/…/locations/…/keyRings/…/cryptoKeys/…) is required"
            )
        self._settings = settings
        self._key_name = settings.key_name.strip("/")
        self._client = client
        self._token: str | None = None

    async def _access_token(self) -> str:
        if self._token is not None:
            return self._token
        credentials = self._settings.credentials_file or (
            Path(value) if (value := env("GOOGLE_APPLICATION_CREDENTIALS")) else None
        )
        if credentials is not None:
            info = cast("dict[str, Any]", orjson.loads(credentials.read_bytes()))
            if info.get("type") != "service_account":
                raise KeyProviderError("the credentials file must be a service-account key")
            request = self._client.build_request(
                "POST",
                TOKEN_URL,
                data={"grant_type": JWT_BEARER, "assertion": service_account_assertion(info, now=int(time.time()))},
            )
            response = await send(self._client, request, "Google token request")
        else:
            request = self._client.build_request("GET", METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
            response = await send(self._client, request, "metadata server token request")
        token = response.json().get("access_token")
        if not isinstance(token, str):
            raise KeyProviderError("Google returned no access token")
        self._token = token
        return token

    async def _call(self, operation: str, body: Mapping[str, str]) -> dict[str, Any]:
        url = f"{self._settings.endpoint.rstrip('/')}/v1/{self._key_name}:{operation}"
        payload = {**body, "additionalAuthenticatedData": base64.b64encode(WRAP_CONTEXT.encode()).decode()}
        request = self._client.build_request(
            "POST", url, json=payload, headers={"Authorization": f"Bearer {await self._access_token()}"}
        )
        response = await send(self._client, request, f"Cloud KMS {operation}")
        return cast("dict[str, Any]", response.json())

    async def wrap(self, key: bytes) -> str:
        data = await self._call("encrypt", {"plaintext": base64.b64encode(key).decode()})
        ciphertext = data.get("ciphertext")
        if not isinstance(ciphertext, str):
            raise KeyProviderError("Cloud KMS encrypt returned no ciphertext")
        return ciphertext

    async def unwrap(self, wrapped: str) -> bytes:
        data = await self._call("decrypt", {"ciphertext": wrapped})
        plaintext = data.get("plaintext")
        if not isinstance(plaintext, str):
            raise KeyProviderError("Cloud KMS decrypt returned no plaintext")
        return base64.b64decode(plaintext)

    def describe(self) -> Mapping[str, str]:
        return {"provider": self.name, "endpoint": self._settings.endpoint, "key": self._key_name}

    async def aclose(self) -> None:
        await self._client.aclose()
