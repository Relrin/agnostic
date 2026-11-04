"""AWS KMS: ``Encrypt`` / ``Decrypt`` with a symmetric KMS key, over the KMS JSON API signed with SigV4.

Credentials, in order: ``access_key_id`` / ``secret_access_key`` (``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``
and ``AWS_SESSION_TOKEN``), then web identity (``role_arn`` + ``web_identity_token_file``, or ``AWS_ROLE_ARN`` +
``AWS_WEB_IDENTITY_TOKEN_FILE`` as IRSA sets them on EKS) exchanged at STS for temporary credentials. Every wrap
carries the encryption context ``{"purpose": "agnostic/master-key/v1"}``, which a key policy can require.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import orjson

from agnostic_kernel.aws_sigv4 import sign
from agnostic_kernel.keys import WRAP_CONTEXT, KeyProviderError, env, send
from agnostic_kernel.settings import AwsKmsSettings

SERVICE = "kms"
STS_VERSION = "2011-06-15"
_XML_FIELD = re.compile(
    r"<(AccessKeyId|SecretAccessKey|SessionToken)>([^<]+)</(?:AccessKeyId|SecretAccessKey|SessionToken)>"
)


@dataclass(frozen=True, slots=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


class AwsKmsProvider:
    name = "aws-kms"

    def __init__(self, settings: AwsKmsSettings, client: httpx.AsyncClient) -> None:
        if not settings.key_id:
            raise KeyProviderError("AGNOSTIC_SECRETS__AWS__KEY_ID is required for the aws-kms provider")
        region = settings.region or env("AWS_REGION") or env("AWS_DEFAULT_REGION") or _region_of(settings.key_id)
        if not region:
            raise KeyProviderError("set AGNOSTIC_SECRETS__AWS__REGION (or AWS_REGION), or use a key ARN")
        self._settings = settings
        self._key_id = settings.key_id
        self._region = region
        self._endpoint = (settings.endpoint or f"https://kms.{region}.amazonaws.com").rstrip("/")
        self._client = client
        self._credentials: AwsCredentials | None = None

    async def _resolve_credentials(self) -> AwsCredentials:
        if self._credentials is not None:
            return self._credentials
        settings = self._settings
        access_key = settings.access_key_id or env("AWS_ACCESS_KEY_ID")
        secret = (
            settings.secret_access_key.get_secret_value()
            if settings.secret_access_key is not None
            else env("AWS_SECRET_ACCESS_KEY")
        )
        if access_key and secret:
            token = (
                settings.session_token.get_secret_value()
                if settings.session_token is not None
                else env("AWS_SESSION_TOKEN")
            )
            self._credentials = AwsCredentials(access_key, secret, token)
            return self._credentials
        role_arn = settings.role_arn or env("AWS_ROLE_ARN")
        token_file = settings.web_identity_token_file or env("AWS_WEB_IDENTITY_TOKEN_FILE")
        if role_arn and token_file:
            self._credentials = await self._assume_role(role_arn, str(token_file))
            return self._credentials
        raise KeyProviderError(
            "no AWS credentials: set an access key (AGNOSTIC_SECRETS__AWS__ACCESS_KEY_ID or AWS_ACCESS_KEY_ID) or web "
            "identity (AWS_ROLE_ARN and AWS_WEB_IDENTITY_TOKEN_FILE)"
        )

    async def _assume_role(self, role_arn: str, token_file: str) -> AwsCredentials:
        web_identity = Path(token_file).read_text(encoding="utf-8").strip()  # noqa: ASYNC240
        endpoint = (self._settings.sts_endpoint or f"https://sts.{self._region}.amazonaws.com").rstrip("/")
        request = self._client.build_request(
            "POST",
            endpoint + "/",
            data={
                "Action": "AssumeRoleWithWebIdentity",
                "Version": STS_VERSION,
                "RoleArn": role_arn,
                "RoleSessionName": "agnostic",
                "WebIdentityToken": web_identity,
            },
        )
        response = await send(self._client, request, "STS AssumeRoleWithWebIdentity")
        found = {match.group(1): match.group(2) for match in _XML_FIELD.finditer(response.text)}
        if "AccessKeyId" not in found or "SecretAccessKey" not in found:
            raise KeyProviderError("STS AssumeRoleWithWebIdentity returned no credentials")
        return AwsCredentials(found["AccessKeyId"], found["SecretAccessKey"], found.get("SessionToken"))

    async def _call(self, target: str, body: Mapping[str, Any]) -> dict[str, Any]:
        credentials = await self._resolve_credentials()
        content = orjson.dumps(body)
        url = httpx.URL(self._endpoint + "/")
        headers = sign(
            method="POST",
            url=url,
            headers={"content-type": "application/x-amz-json-1.1", "x-amz-target": f"TrentService.{target}"},
            payload_sha256=hashlib.sha256(content).hexdigest(),
            access_key_id=credentials.access_key_id,
            secret_access_key=credentials.secret_access_key,
            region=self._region,
            service=SERVICE,
            at=datetime.now(UTC),
            session_token=credentials.session_token,
        )
        request = self._client.build_request("POST", url, content=content, headers=headers)
        response = await send(self._client, request, f"AWS KMS {target}")
        return cast("dict[str, Any]", orjson.loads(response.content))

    async def wrap(self, key: bytes) -> str:
        data = await self._call(
            "Encrypt",
            {
                "KeyId": self._key_id,
                "Plaintext": base64.b64encode(key).decode(),
                "EncryptionContext": {"purpose": WRAP_CONTEXT},
            },
        )
        blob = data.get("CiphertextBlob")
        if not isinstance(blob, str):
            raise KeyProviderError("AWS KMS Encrypt returned no ciphertext")
        return blob

    async def unwrap(self, wrapped: str) -> bytes:
        data = await self._call(
            "Decrypt",
            {"KeyId": self._key_id, "CiphertextBlob": wrapped, "EncryptionContext": {"purpose": WRAP_CONTEXT}},
        )
        plaintext = data.get("Plaintext")
        if not isinstance(plaintext, str):
            raise KeyProviderError("AWS KMS Decrypt returned no plaintext")
        return base64.b64decode(plaintext)

    def describe(self) -> Mapping[str, str]:
        return {"provider": self.name, "endpoint": self._endpoint, "key": self._key_id, "region": self._region}

    async def aclose(self) -> None:
        await self._client.aclose()


def _region_of(key_id: str) -> str | None:
    """``arn:aws:kms:<region>:<account>:key/<id>`` → ``<region>``."""
    parts = key_id.split(":")
    return parts[3] if len(parts) > 3 and parts[0] == "arn" else None  # noqa: PLR2004
