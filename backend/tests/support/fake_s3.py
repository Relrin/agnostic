"""In-memory S3-compatible storage (path-style ``/<bucket>/<key>``) that checks SigV4-signed requests the way S3
would reject unsigned or tampered ones, honours Object Lock headers, and records every request.

Also a SIEM webhook receiver that can be told to fail, for at-least-once delivery tests.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, Response


@dataclass
class StoredObject:
    data: bytes
    content_type: str
    lock_mode: str | None = None
    retain_until: datetime | None = None


def _error(status: int, code: str, message: str) -> Response:
    body = f"<?xml version='1.0' encoding='UTF-8'?><Error><Code>{code}</Code><Message>{message}</Message></Error>"
    return Response(body, status_code=status, media_type="application/xml")


@dataclass
class FakeS3:
    buckets: dict[str, dict[str, StoredObject]] = field(default_factory=lambda: {"audit-archive": {}})
    access_key_id: str = "AKIDEXAMPLEAGNOSTIC"
    requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    fail_puts: int = 0
    corrupt_reads: bool = False

    def __post_init__(self) -> None:
        self.app = self._build()

    def objects(self, bucket: str = "audit-archive") -> dict[str, StoredObject]:
        return self.buckets[bucket]

    def _check(self, request: Request, body: bytes) -> Response | None:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith(f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/"):
            return _error(403, "InvalidAccessKeyId", "The AWS access key id you provided does not exist.")
        if "SignedHeaders=" not in authorization or "Signature=" not in authorization:
            return _error(403, "AccessDenied", "Malformed Authorization header.")
        signed = authorization.split("SignedHeaders=", 1)[1].split(",", 1)[0].split(";")
        if not {"host", "x-amz-date", "x-amz-content-sha256"} <= set(signed):
            return _error(403, "AccessDenied", "Required headers are not signed.")
        if request.headers.get("x-amz-content-sha256") != hashlib.sha256(body).hexdigest():
            return _error(400, "XAmzContentSHA256Mismatch", "The provided content SHA-256 does not match.")
        return None

    def _build(self) -> FastAPI:  # noqa: C901
        app = FastAPI()

        @app.api_route("/{bucket}/{key:path}", methods=["GET", "PUT", "HEAD", "DELETE"])
        async def handle(bucket: str, key: str, request: Request) -> Response:  # noqa: C901, PLR0911
            body = await request.body()
            self.requests.append({"method": request.method, "key": key, "headers": dict(request.headers)})
            refused = self._check(request, body)
            if refused is not None:
                return refused
            objects = self.buckets.get(bucket)
            if objects is None:
                return _error(404, "NoSuchBucket", "The specified bucket does not exist.")
            if request.method == "PUT":
                if self.fail_puts:
                    self.fail_puts -= 1
                    return _error(503, "SlowDown", "Please reduce your request rate.")
                md5 = request.headers.get("content-md5")
                if md5 and md5 != base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode():
                    return _error(400, "BadDigest", "The Content-MD5 you specified did not match.")
                mode = request.headers.get("x-amz-object-lock-mode")
                until = request.headers.get("x-amz-object-lock-retain-until-date")
                if (mode is None) != (until is None):
                    return _error(400, "InvalidRequest", "Object Lock mode and retain-until date go together.")
                objects[key] = StoredObject(
                    data=body,
                    content_type=request.headers.get("content-type", "application/octet-stream"),
                    lock_mode=mode,
                    retain_until=datetime.fromisoformat(until) if until else None,
                )
                return Response(
                    status_code=200, headers={"ETag": f'"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'}
                )
            stored = objects.get(key)
            if stored is None:
                return _error(404, "NoSuchKey", "The specified key does not exist.")
            if request.method == "DELETE":
                if stored.lock_mode == "COMPLIANCE" and stored.retain_until and stored.retain_until > datetime.now(UTC):
                    return _error(403, "AccessDenied", "Object is WORM protected.")
                del objects[key]
                return Response(status_code=204)
            if request.method == "HEAD":
                return Response(status_code=200, headers={"Content-Length": str(len(stored.data))})
            data = stored.data[:-1] + bytes([stored.data[-1] ^ 1]) if self.corrupt_reads else stored.data
            return Response(data, status_code=200, media_type=stored.content_type)

        return app


@dataclass
class FakeReceiver:
    """An HTTPS webhook / OTLP endpoint that records what it accepts and fails ``fail_next`` requests first."""

    fail_next: int = 0
    received: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    refused: int = 0

    def __post_init__(self) -> None:
        app = FastAPI()

        @app.post("/{path:path}")
        async def accept(path: str, request: Request) -> Response:
            body = await request.body()
            if self.fail_next:
                self.fail_next -= 1
                self.refused += 1
                return Response("receiver unavailable", status_code=503)
            self.received.append({"path": path, "body": body, "headers": dict(request.headers)})
            return Response(status_code=204)

        self.app = app
