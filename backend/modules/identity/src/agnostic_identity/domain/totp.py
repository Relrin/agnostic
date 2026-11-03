"""Time-based one-time passwords (RFC 6238 on top of RFC 4226 HOTP): SHA-1, 30-second steps, 6 digits.

These are the parameters every authenticator app supports. Verification accepts the previous and the next step
(clock drift) and compares in constant time; the caller remembers the accepted step so a code can't be used twice.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
WINDOW = 1
SECRET_BYTES = 20
"""160 bits, the HMAC-SHA-1 block-friendly size RFC 4226 recommends."""


class InvalidSecretError(ValueError):
    pass


def new_secret() -> str:
    """A random secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def decode_secret(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    try:
        return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except ValueError as exc:
        raise InvalidSecretError("not a base32 secret") from exc


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 10**digits).zfill(digits)


def time_step(at: float, step: int = STEP_SECONDS) -> int:
    return int(at // step)


def totp(key: bytes, at: float, *, step: int = STEP_SECONDS, digits: int = DIGITS) -> str:
    return hotp(key, time_step(at, step), digits)


def normalize_code(code: str) -> str:
    return "".join(code.split()).replace("-", "")


def verify(key: bytes, code: str, at: float, *, window: int = WINDOW, step: int = STEP_SECONDS) -> int | None:
    """The time step ``code`` matches (within ``window`` steps of ``at``), or ``None``.

    Every candidate is computed and compared, so the time taken doesn't depend on which step matched.
    """
    candidate = normalize_code(code)
    if len(candidate) != DIGITS or not candidate.isdigit():
        return None
    current = time_step(at, step)
    matched: int | None = None
    for counter in range(current - window, current + window + 1):
        if hmac.compare_digest(hotp(key, counter).encode(), candidate.encode()) and matched is None:
            matched = counter
    return matched


def otpauth_uri(secret: str, *, account: str, issuer: str) -> str:
    """The ``otpauth://`` URI authenticator apps scan as a QR code."""
    label = quote(f"{issuer}:{account}", safe="@:")
    params = {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS}
    return f"otpauth://totp/{label}?{urlencode(params)}"
