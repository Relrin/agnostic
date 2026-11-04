"""A minimal S3 client (PUT, GET, HEAD, DELETE) signed with AWS Signature Version 4, over httpx.

Path-style URLs (``<endpoint>/<bucket>/<key>``) work with AWS and with S3-compatible stores (MinIO, Ceph, R2,
Wasabi). Objects can be written with S3 Object Lock (governance or compliance mode with a retain-until date).
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from agnostic_audit.application.ports import ObjectNotFoundError, ObjectStore, ObjectStoreError, StoredObject
from agnostic_audit.domain.archive import ArchiveTarget
from agnostic_audit.infrastructure.http import AuditHttp
from agnostic_kernel.aws_sigv4 import EMPTY_SHA256, sign

SERVICE = "s3"
_ERROR = re.compile(r"<(Code|Message)>([^<]*)</\1>")


def _describe(response: httpx.Response) -> str:
    found = dict(_ERROR.findall(response.text[:4000])) if response.content else {}
    detail = ": ".join(part for part in (found.get("Code"), found.get("Message")) if part)
    return f"HTTP {response.status_code}" + (f" ({detail})" if detail else "")


class S3ObjectStore:
    def __init__(self, client: httpx.AsyncClient, target: ArchiveTarget) -> None:
        self._client = client
        self._target = target

    def _url(self, key: str) -> httpx.URL:
        endpoint = self._target.endpoint.rstrip("/")
        return httpx.URL(f"{endpoint}/{quote(self._target.bucket, safe='')}/{quote(key, safe='/~')}")

    async def _request(
        self, method: str, key: str, *, content: bytes = b"", headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        url = self._url(key)
        payload_sha256 = hashlib.sha256(content).hexdigest() if content else EMPTY_SHA256
        signed = sign(
            method=method,
            url=url,
            headers=headers or {},
            payload_sha256=payload_sha256,
            access_key_id=self._target.access_key_id,
            secret_access_key=self._target.secret_access_key,
            region=self._target.region,
            service=SERVICE,
            at=datetime.now(UTC),
        )
        try:
            response = await self._client.request(method, url, content=content or None, headers=signed)
        except httpx.HTTPError as exc:
            msg = f"{self._target.endpoint} is unreachable: {exc}"
            raise ObjectStoreError(msg) from exc
        if response.status_code == 404:  # noqa: PLR2004
            raise ObjectNotFoundError(f"s3://{self._target.bucket}/{key} doesn't exist")
        if response.status_code >= 300:  # noqa: PLR2004
            msg = f"{method} s3://{self._target.bucket}/{key} failed: {_describe(response)}"
            raise ObjectStoreError(msg)
        return response

    async def put(self, key: str, data: bytes, *, content_type: str, retain_until: datetime | None = None) -> None:
        headers = {
            "content-type": content_type,
            "content-md5": base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode(),
        }
        if retain_until is not None and self._target.object_lock_mode in {"governance", "compliance"}:
            headers["x-amz-object-lock-mode"] = self._target.object_lock_mode.upper()
            headers["x-amz-object-lock-retain-until-date"] = retain_until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        _ = await self._request("PUT", key, content=data, headers=headers)

    async def get(self, key: str) -> bytes:
        return (await self._request("GET", key)).content

    async def head(self, key: str) -> StoredObject:
        response = await self._request("HEAD", key)
        return StoredObject(size=int(response.headers.get("content-length", "0")), etag=response.headers.get("etag"))

    async def delete(self, key: str) -> None:
        _ = await self._request("DELETE", key)


class S3ObjectStores:
    def __init__(self, http: AuditHttp) -> None:
        self._http = http

    def open(self, target: ArchiveTarget) -> ObjectStore:
        return S3ObjectStore(self._http.client, target)
