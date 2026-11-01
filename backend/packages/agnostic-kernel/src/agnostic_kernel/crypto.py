"""Secrets at rest and opaque tokens.

:class:`SecretBox` does envelope encryption: every secret gets its own random data key (AES-256-GCM), and
the data key is wrapped by the key-encryption key from ``AGNOSTIC_SECRETS__MASTER_KEY``. Sealed values are text:
``v1.<kek id>.<wrapped data key>.<nonce>.<ciphertext>`` (base64url parts), so they fit any text column. A KMS or
Vault key provider can replace the local KEK later without changing the format.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agnostic_kernel.logging import get_logger
from agnostic_kernel.settings import SecretsSettings

log = get_logger(__name__)

_VERSION = "v1"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_DEV_KEY = hashlib.sha256(b"agnostic-insecure-development-master-key").digest()


class SecretsConfigError(RuntimeError):
    """The master key is missing or malformed."""


class SecretDecryptionError(RuntimeError):
    """A sealed value can't be opened (wrong master key, or tampered)."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_master_key(settings: SecretsSettings, *, environment: str) -> bytes:
    raw: str | None = None
    if settings.master_key is not None:
        raw = settings.master_key.get_secret_value()
    elif settings.master_key_file is not None:
        raw = settings.master_key_file.read_text(encoding="utf-8")
    if raw is None:
        if environment == "production":
            msg = "AGNOSTIC_SECRETS__MASTER_KEY (or AGNOSTIC_SECRETS__MASTER_KEY_FILE) is required in production"
            raise SecretsConfigError(msg)
        log.warning("secrets.development_master_key", detail="set AGNOSTIC_SECRETS__MASTER_KEY before real use")
        return _DEV_KEY
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretsConfigError("the master key must be base64") from exc
    if len(key) != _KEY_BYTES:
        msg = f"the master key must be {_KEY_BYTES} bytes, got {len(key)}"
        raise SecretsConfigError(msg)
    return key


class SecretBox:
    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != _KEY_BYTES:
            msg = f"master key must be {_KEY_BYTES} bytes"
            raise SecretsConfigError(msg)
        self._kek = AESGCM(master_key)
        self._kek_id = hashlib.sha256(master_key).hexdigest()[:8]

    @property
    def key_id(self) -> str:
        return self._kek_id

    def seal(self, plaintext: bytes) -> str:
        data_key = AESGCM.generate_key(bit_length=256)
        wrap_nonce = os.urandom(_NONCE_BYTES)
        wrapped = wrap_nonce + self._kek.encrypt(wrap_nonce, data_key, self._kek_id.encode())
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, None)
        return ".".join((_VERSION, self._kek_id, _b64e(wrapped), _b64e(nonce), _b64e(ciphertext)))

    def open(self, sealed: str) -> bytes:
        parts = sealed.split(".")
        if len(parts) != 5 or parts[0] != _VERSION:  # noqa: PLR2004
            raise SecretDecryptionError("unknown sealed-secret format")
        _, kek_id, wrapped_text, nonce_text, ciphertext_text = parts
        if kek_id != self._kek_id:
            msg = f"sealed with master key {kek_id}, but the configured master key is {self._kek_id}"
            raise SecretDecryptionError(msg)
        try:
            wrapped = _b64d(wrapped_text)
            data_key = self._kek.decrypt(wrapped[:_NONCE_BYTES], wrapped[_NONCE_BYTES:], kek_id.encode())
            return AESGCM(data_key).decrypt(_b64d(nonce_text), _b64d(ciphertext_text), None)
        except (InvalidTag, ValueError, binascii.Error) as exc:
            raise SecretDecryptionError("the sealed secret is corrupted") from exc


def new_token(nbytes: int = 32) -> str:
    """A URL-safe random token (sessions, invitations, password resets)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Store this instead of the token: lookups stay possible, a database dump stays useless."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
