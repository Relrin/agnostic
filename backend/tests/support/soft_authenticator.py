"""A software WebAuthn authenticator (``none`` attestation, ES256) that answers the API's options like a browser."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class SoftAuthenticator:
    def __init__(self, origin: str = "http://agnostic.test", rp_id: str = "agnostic.test") -> None:
        self.origin = origin
        self.rp_id = rp_id
        self.credential_id = secrets.token_bytes(16)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.sign_count = 0

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def create(self, options: dict[str, Any]) -> dict[str, Any]:
        """``navigator.credentials.create()`` for the server's creation options."""
        assert options["rp"]["id"] == self.rp_id
        rp_hash = hashlib.sha256(self.rp_id.encode()).digest()
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_key()
        auth_data = rp_hash + bytes([0x41]) + struct.pack(">I", self.sign_count) + attested
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", options["challenge"])),
                "attestationObject": b64url(attestation),
                "transports": ["usb"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict[str, Any]) -> dict[str, Any]:
        """``navigator.credentials.get()`` for the server's request options."""
        assert options["rpId"] == self.rp_id
        self.sign_count += 1
        auth_data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x01]) + struct.pack(">I", self.sign_count)
        client_data = self._client_data("webauthn.get", options["challenge"])
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }
