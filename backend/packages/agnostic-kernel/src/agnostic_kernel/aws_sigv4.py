"""AWS Signature Version 4 request signing, shared by the S3 archive client and the AWS KMS key provider."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

ALGORITHM = "AWS4-HMAC-SHA256"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def signing_key(secret_access_key: str, date: str, region: str, service: str) -> bytes:
    key = _hmac(("AWS4" + secret_access_key).encode(), date)
    return _hmac(_hmac(_hmac(key, region), service), "aws4_request")


def canonical_uri(path: str) -> str:
    return quote(path, safe="/~")


def sign(
    *,
    method: str,
    url: httpx.URL,
    headers: Mapping[str, str],
    payload_sha256: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    service: str,
    at: datetime,
    session_token: str | None = None,
) -> dict[str, str]:
    """The request's headers plus ``x-amz-date``, ``x-amz-content-sha256`` and ``Authorization``.

    ``session_token`` (temporary credentials from STS) is sent and signed as ``x-amz-security-token``.
    """
    amz_date = at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    signed: dict[str, str] = {key.lower(): " ".join(value.strip().split()) for key, value in headers.items()}
    signed |= {"host": url.netloc.decode(), "x-amz-date": amz_date, "x-amz-content-sha256": payload_sha256}
    if session_token:
        signed["x-amz-security-token"] = session_token
    names = sorted(signed)
    query = "&".join(
        f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}" for key, value in sorted(url.params.multi_items())
    )
    canonical = "\n".join(
        (
            method.upper(),
            canonical_uri(url.path),
            query,
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            payload_sha256,
        )
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join((ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()))
    key = signing_key(secret_access_key, date, region, service)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        **{name: signed[name] for name in names},
        "authorization": (
            f"{ALGORITHM} Credential={access_key_id}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
        ),
    }
