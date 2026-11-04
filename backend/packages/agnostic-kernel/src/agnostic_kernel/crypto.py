"""Secrets at rest and opaque tokens.

:class:`SecretBox` does envelope encryption: every secret gets its own random data key (AES-256-GCM), and
the data key is wrapped by the master key (the key-encryption key). Sealed values are text:
``v1.<kek id>.<wrapped data key>.<nonce>.<ciphertext>`` (base64url parts), so they fit any text column.

The box holds a key ring: it seals with the current master key and opens values sealed with any configured key,
so a master key can be rotated (``agnostic secrets rotate``) while old values stay readable. Where the master key
comes from (the configuration, or a KMS that unwraps it) is up to :mod:`agnostic_kernel.keys`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
from collections.abc import Iterable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agnostic_kernel.logging import get_logger
from agnostic_kernel.settings import SecretsSettings

log = get_logger(__name__)

_VERSION = "v1"
KEY_BYTES = 32
_NONCE_BYTES = 12
DEVELOPMENT_KEY = hashlib.sha256(b"agnostic-insecure-development-master-key").digest()


class SecretsConfigError(RuntimeError):
    """The master key is missing or malformed."""


class SecretDecryptionError(RuntimeError):
    """A sealed value can't be opened (wrong master key, or tampered)."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def key_id(master_key: bytes) -> str:
    """Short public identifier of a master key, recorded in every value sealed with it."""
    return hashlib.sha256(master_key).hexdigest()[:8]


def decode_local_key(raw: str) -> bytes:
    """A master key as configured for the ``local`` provider: 32 bytes, base64."""
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretsConfigError("the master key must be base64") from exc
    if len(key) != KEY_BYTES:
        msg = f"the master key must be {KEY_BYTES} bytes, got {len(key)}"
        raise SecretsConfigError(msg)
    return key


def encode_local_key(key: bytes) -> str:
    return base64.b64encode(key).decode()


def generate_master_key() -> bytes:
    return os.urandom(KEY_BYTES)


def load_master_key(settings: SecretsSettings, *, environment: str) -> bytes:
    """The current master key of the ``local`` provider (KMS-wrapped keys go through :mod:`agnostic_kernel.keys`)."""
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
        return DEVELOPMENT_KEY
    return decode_local_key(raw)


class SecretBox:
    def __init__(self, master_key: bytes, previous: Iterable[bytes] = ()) -> None:
        keys = [master_key, *previous]
        for key in keys:
            if len(key) != KEY_BYTES:
                msg = f"master key must be {KEY_BYTES} bytes"
                raise SecretsConfigError(msg)
        self._kek_id = key_id(master_key)
        self._keys: dict[str, bytes] = {}
        for key in keys:
            _ = self._keys.setdefault(key_id(key), key)
        self._ring = {kid: AESGCM(key) for kid, key in self._keys.items()}
        self._kek = self._ring[self._kek_id]

    @property
    def key_id(self) -> str:
        """Id of the current master key (the one new values are sealed with)."""
        return self._kek_id

    @property
    def key_ids(self) -> tuple[str, ...]:
        """Every key that can open values, current first."""
        return tuple(self._ring)

    def sealed_with(self, sealed: str) -> str | None:
        """The master-key id a sealed value names, or ``None`` when it isn't a sealed value."""
        parts = sealed.split(".")
        if len(parts) != 5 or parts[0] != _VERSION:  # noqa: PLR2004
            return None
        return parts[1]

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
        kek = self._ring.get(kek_id)
        if kek is None:
            msg = f"sealed with master key {kek_id}, which isn't configured (current: {self._kek_id})"
            raise SecretDecryptionError(msg)
        try:
            wrapped = _b64d(wrapped_text)
            data_key = kek.decrypt(wrapped[:_NONCE_BYTES], wrapped[_NONCE_BYTES:], kek_id.encode())
            return AESGCM(data_key).decrypt(_b64d(nonce_text), _b64d(ciphertext_text), None)
        except (InvalidTag, ValueError, binascii.Error) as exc:
            raise SecretDecryptionError("the sealed secret is corrupted") from exc

    def reseal(self, sealed: str) -> str | None:
        """``sealed`` re-sealed with the current key, or ``None`` when it already is."""
        if self.sealed_with(sealed) == self._kek_id:
            return None
        return self.seal(self.open(sealed))

    def derive(self, context: bytes) -> str:
        """A stable secret derived from the current master key for ``context`` (hex)."""
        return hashlib.sha256(context + self._keys[self._kek_id]).hexdigest()

    def derive_all(self, context: bytes) -> tuple[str, ...]:
        """:meth:`derive` for the current key, then for every retired key (to accept values made before rotation)."""
        return tuple(hashlib.sha256(context + key).hexdigest() for key in self._keys.values())


def new_token(nbytes: int = 32) -> str:
    """A URL-safe random token (sessions, invitations, password resets)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Store this instead of the token: lookups stay possible, a database dump stays useless."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
