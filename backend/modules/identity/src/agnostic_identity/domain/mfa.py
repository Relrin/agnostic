"""Second factors: authenticator apps (TOTP), security keys and passkeys (WebAuthn), recovery codes. No I/O."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
"""31 characters without look-alikes (no i, l, o, 0, 1): 16 of them are ~79 bits."""
_RECOVERY_LENGTH = 16
MAX_LABEL = 120


class FactorKind(StrEnum):
    TOTP = "totp"
    WEBAUTHN = "webauthn"


class MfaMethod(StrEnum):
    """What a person can answer a sign-in challenge with."""

    TOTP = "totp"
    WEBAUTHN = "webauthn"
    RECOVERY_CODE = "recovery_code"


@dataclass(frozen=True, slots=True)
class Factor:
    id: str
    kind: FactorKind
    label: str
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class WebAuthnCredential:
    """A registered security key or passkey."""

    factor_id: str
    credential_id: bytes
    public_key: bytes
    """COSE-encoded public key."""
    sign_count: int
    transports: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NewWebAuthnCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: tuple[str, ...]
    aaguid: str


def methods_for(factors: list[Factor], *, has_recovery_codes: bool) -> tuple[MfaMethod, ...]:
    kinds = {factor.kind for factor in factors}
    methods = [MfaMethod(kind.value) for kind in (FactorKind.TOTP, FactorKind.WEBAUTHN) if kind in kinds]
    if has_recovery_codes:
        methods.append(MfaMethod.RECOVERY_CODE)
    return tuple(methods)


def new_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Single-use codes shown once, formatted ``xxxx-xxxx-xxxx-xxxx``."""
    codes: list[str] = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        codes.append("-".join(raw[index : index + 4] for index in range(0, _RECOVERY_LENGTH, 4)))
    return codes


def normalize_recovery_code(code: str) -> str:
    """Case, spaces and dashes don't matter when typing a recovery code back."""
    return "".join(character for character in code.lower() if character.isalnum())


def clean_label(label: str | None, default: str) -> str:
    cleaned = " ".join((label or "").split())[:MAX_LABEL]
    return cleaned or default
