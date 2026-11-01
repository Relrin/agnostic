"""Adapters: talking to runtimes (through ``agnostic-agentos-client``) and RS256 key material."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ssl
import time
from collections.abc import Mapping
from typing import Any, cast

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agnostic_agentos_client import AgentOSClient
from agnostic_agentos_client.auth import Auth, NoAuth
from agnostic_instances.application.ports import GeneratedKey, Target
from agnostic_instances.domain.instances import AuthMode, Discovery

PROBE_TIMEOUT = 5.0


def tls_verify(target: Target) -> bool | ssl.SSLContext:
    if not target.tls_verify:
        return False
    if target.ca_bundle_pem:
        return ssl.create_default_context(cadata=target.ca_bundle_pem)
    return True


class _HeaderAuth:
    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    async def headers(self) -> dict[str, str]:
        return dict(self._headers)


class HttpRuntimeClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self, target: Target, auth: Auth | None = None) -> AgentOSClient:
        return AgentOSClient(
            target.endpoint_url,
            auth=auth or NoAuth(),
            timeout=PROBE_TIMEOUT,
            retries=0,
            verify=tls_verify(target),
            transport=self._transport,
        )

    async def resolve(self, host: str, port: int) -> list[str]:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port)
        return sorted({str(info[4][0]) for info in infos})

    async def health(self, target: Target) -> float:
        async with self._client(target) as client:
            started = time.perf_counter()
            _ = await client.health()
            return (time.perf_counter() - started) * 1000

    async def info(self, target: Target) -> Discovery:
        async with self._client(target) as client:
            info = await client.info()
        mode = str(info.auth_mode or "none")
        return Discovery(
            os_id=info.os_id,
            name=info.name,
            agno_version=info.agno_version,
            os_version=info.os_version,
            auth_mode=AuthMode(mode) if mode in {m.value for m in AuthMode} else AuthMode.UNKNOWN,
            user_isolation=info.user_isolation,
            agent_count=info.agent_count or 0,
            team_count=info.team_count or 0,
            workflow_count=info.workflow_count or 0,
            mcp_enabled=bool(info.mcp is not None and info.mcp.enabled),
        )

    async def get_json(
        self, target: Target, path: str, headers: Mapping[str, str], params: Mapping[str, str | int] | None = None
    ) -> Any:  # noqa: ANN401
        async with self._client(target, _HeaderAuth(headers)) as client:
            return await client.get_json(path, params=params)

    async def probe(
        self, target: Target, path: str, headers: Mapping[str, str], params: Mapping[str, str | int] | None = None
    ) -> tuple[int, str]:
        async with self._client(target, _HeaderAuth(headers)) as client:
            return await client.probe(path, params=params)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _int_b64(value: int) -> str:
    return _b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class Rs256Signer:
    """RS256 with 3072-bit keys; ``kid`` is the RFC 7638 JWK thumbprint."""

    alg = "RS256"

    def generate(self) -> GeneratedKey:
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        private_pem = private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        public_pem = (
            private.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        return GeneratedKey(kid=self._thumbprint(public_pem), public_pem=public_pem, private_pem=private_pem)

    def _numbers(self, public_pem: str) -> rsa.RSAPublicNumbers:
        key = serialization.load_pem_public_key(public_pem.encode())
        assert isinstance(key, rsa.RSAPublicKey)
        return key.public_numbers()

    def _thumbprint(self, public_pem: str) -> str:
        numbers = self._numbers(public_pem)
        canonical = f'{{"e":"{_int_b64(numbers.e)}","kty":"RSA","n":"{_int_b64(numbers.n)}"}}'
        return _b64(hashlib.sha256(canonical.encode()).digest())

    def sign(self, private_pem: str, kid: str, claims: Mapping[str, Any]) -> str:
        return jwt.encode(dict(claims), private_pem, algorithm=self.alg, headers={"kid": kid})

    def jwk(self, public_pem: str, kid: str) -> dict[str, str]:
        numbers = self._numbers(public_pem)
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": self.alg,
            "kid": kid,
            "n": _int_b64(numbers.n),
            "e": _int_b64(numbers.e),
        }

    def verify(
        self, token: str, keys: Mapping[str, str], audience: str | None
    ) -> tuple[str | None, dict[str, Any] | None, str | None]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            return None, None, f"Not a JWT: {exc}"
        kid = cast("str | None", header.get("kid"))
        pem = keys.get(kid or "") if kid else next(iter(keys.values()), None)
        if pem is None:
            return kid, None, "Signed with a key this instance doesn't have (kid not found)."
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                pem,
                algorithms=[self.alg],
                audience=audience,
                options={"verify_aud": audience is not None},
                leeway=10,
            )
        except jwt.ExpiredSignatureError:
            unverified: dict[str, Any] = jwt.decode(token, options={"verify_signature": False})
            return kid, unverified, "The signature is valid but the token has expired."
        except jwt.InvalidAudienceError:
            unverified = jwt.decode(token, options={"verify_signature": False})
            return kid, unverified, f"The audience isn't this instance ({audience})."
        except jwt.PyJWTError as exc:
            return kid, None, f"Invalid: {exc}"
        return kid, claims, None
