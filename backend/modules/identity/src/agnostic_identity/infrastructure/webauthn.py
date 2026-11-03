"""WebAuthn (security keys and passkeys) with the ``webauthn`` package. The relying party is the public URL's host."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Any, cast
from urllib.parse import urlsplit

import orjson
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from agnostic_identity.domain.mfa import NewWebAuthnCredential, WebAuthnCredential

RP_NAME = "Agnostic"
TIMEOUT_MS = 120_000
_TRANSPORTS = {transport.value for transport in AuthenticatorTransport}


def _transports(values: Sequence[str]) -> list[AuthenticatorTransport]:
    return [AuthenticatorTransport(value) for value in values if value in _TRANSPORTS]


class PyWebAuthnVerifier:
    def __init__(self, public_url: str) -> None:
        parts = urlsplit(public_url)
        self._rp_id = parts.hostname or "localhost"
        self._origin = f"{parts.scheme}://{parts.netloc}"

    def registration_options(
        self, *, user_id: str, user_name: str, display_name: str, exclude: Sequence[bytes]
    ) -> tuple[dict[str, Any], bytes]:
        options = generate_registration_options(
            rp_id=self._rp_id,
            rp_name=RP_NAME,
            user_name=user_name,
            user_id=user_id.encode(),
            user_display_name=display_name,
            timeout=TIMEOUT_MS,
            exclude_credentials=[PublicKeyCredentialDescriptor(id=item) for item in exclude],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.DISCOURAGED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        return cast("dict[str, Any]", orjson.loads(options_to_json(options))), options.challenge

    def verify_registration(self, credential: Mapping[str, Any], challenge: bytes) -> NewWebAuthnCredential:
        try:
            verified = verify_registration_response(
                credential=dict(credential),
                expected_challenge=challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
            )
        except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"the security key's registration didn't verify ({exc})") from exc
        response = cast("dict[str, Any]", credential.get("response") or {})
        transports = cast("list[str]", response.get("transports") or [])
        return NewWebAuthnCredential(
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=tuple(str(item) for item in transports),
            aaguid=verified.aaguid,
        )

    def authentication_options(self, credentials: Sequence[WebAuthnCredential]) -> tuple[dict[str, Any], bytes]:
        options = generate_authentication_options(
            rp_id=self._rp_id,
            timeout=TIMEOUT_MS,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=item.credential_id, transports=_transports(item.transports))
                for item in credentials
            ],
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        return cast("dict[str, Any]", orjson.loads(options_to_json(options))), options.challenge

    def credential_id(self, credential: Mapping[str, Any]) -> bytes | None:
        raw = credential.get("rawId") or credential.get("id")
        if not isinstance(raw, str):
            return None
        try:
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except ValueError:
            return None

    def verify_authentication(self, credential: Mapping[str, Any], challenge: bytes, stored: WebAuthnCredential) -> int:
        try:
            verified = verify_authentication_response(
                credential=dict(credential),
                expected_challenge=challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                credential_public_key=stored.public_key,
                credential_current_sign_count=stored.sign_count,
            )
        except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"the security key's assertion didn't verify ({exc})") from exc
        return verified.new_sign_count
