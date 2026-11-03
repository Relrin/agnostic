"""Google's OAuth token endpoint and the Admin SDK Directory API (groups, members, users), in memory.

The token endpoint checks the service-account JWT like Google does: RS256 signature with the key it handed out,
the delegated admin (``sub``), the audience and exactly the two read-only directory scopes. Lists are paged two
items at a time so callers have to follow ``nextPageToken``. The key pair is generated at runtime.
"""

from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass, field
from functools import cache
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx
import orjson
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_PREFIX = "/admin/directory/v1"
SCOPES = {
    "https://www.googleapis.com/auth/admin.directory.group.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
}
PAGE_SIZE = 2


@cache
def _service_account_key() -> rsa.RSAPrivateKey:
    """One key per test session: generating RSA keys is slow, and every stack has a fake Google."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class FakeGoogle:
    admin: str = "admin@localhost.company"
    client_email: str = "directory-sync@agnostic-test.iam.gserviceaccount.com"
    customer: str = "my_customer"
    groups: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    """Group id → ``{"id", "email", "name"}``."""
    members: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    """Group id → member emails."""
    users: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    """Primary email → ``{"id", "primaryEmail", "name", "suspended", "aliases"}``."""
    token_requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    api_requests: list[str] = field(default_factory=list[str])
    _issued: set[str] = field(default_factory=set[str])
    _key: rsa.RSAPrivateKey = field(default_factory=_service_account_key)

    def add_group(self, group_id: str, email: str, name: str, members: list[str]) -> None:
        self.groups[group_id] = {"id": group_id, "email": email, "name": name}
        self.members[group_id] = list(members)

    def add_user(self, email: str, name: str, *, suspended: bool = False, aliases: tuple[str, ...] = ()) -> None:
        self.users[email] = {
            "id": f"1{len(self.users):04d}",
            "primaryEmail": email,
            "name": {"fullName": name},
            "suspended": suspended,
            "aliases": list(aliases),
        }

    def revoke_tokens(self) -> None:
        """Every access token handed out so far stops working (delegation revoked, key deleted)."""
        self._issued.clear()

    def service_account_json(self) -> str:
        pem = self._key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        return orjson.dumps(
            {
                "type": "service_account",
                "project_id": "agnostic-test",
                "private_key_id": "k1",
                "private_key": pem,
                "client_email": self.client_email,
                "token_uri": "https://evil.test/token",
            }
        ).decode()

    def transport(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:  # noqa: C901, PLR0911  (one answer per endpoint)
        if str(request.url) == TOKEN_URL and request.method == "POST":
            return self._token(request)
        if request.url.host != "admin.googleapis.com":
            raise httpx.ConnectError(f"Connection refused: {request.url.host}", request=request)
        self.api_requests.append(f"{request.method} {request.url.path}")
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if bearer not in self._issued:
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
        path = unquote(request.url.path.removeprefix(API_PREFIX))
        params = request.url.params
        if path == "/groups":
            if params.get("customer") != self.customer:
                return httpx.Response(400, json={"error": {"code": 400, "message": "Bad Request"}})
            return self._page("groups", list(self.groups.values()), params.get("pageToken"))
        if path.startswith("/groups/") and path.endswith("/members"):
            group_id = path.split("/")[2]
            if group_id not in self.groups:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Resource Not Found: groupKey"}})
            items = [
                {"email": email, "type": "USER", "status": "ACTIVE", "role": "MEMBER"}
                for email in self.members.get(group_id, [])
            ]
            return self._page("members", items, params.get("pageToken"))
        if path == "/users":
            return self._page("users", list(self.users.values()), params.get("pageToken"))
        if path.startswith("/users/"):
            user = self.users.get(path.removeprefix("/users/"))
            if user is None:
                return httpx.Response(404, json={"error": {"code": 404, "message": "Resource Not Found: userKey"}})
            return httpx.Response(200, json=user)
        return httpx.Response(404, json={"error": {"code": 404, "message": "Not Found"}})

    @staticmethod
    def _page(key: str, items: list[Any], token: str | None) -> httpx.Response:
        start = int(token or 0)
        body: dict[str, Any] = {"kind": f"admin#directory#{key}", key: items[start : start + PAGE_SIZE]}
        if start + PAGE_SIZE < len(items):
            body["nextPageToken"] = str(start + PAGE_SIZE)
        return httpx.Response(200, json=body)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        if form.get("grant_type") != "urn:ietf:params:oauth:grant-type:jwt-bearer":
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        header_text, claims_text, signature_text = form.get("assertion", "..").split(".")
        try:
            self._key.public_key().verify(
                _b64d(signature_text),
                f"{header_text}.{claims_text}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Invalid JWT Signature."})
        header, claims = orjson.loads(_b64d(header_text)), orjson.loads(_b64d(claims_text))
        now = time.time()
        problems = [
            header.get("alg") != "RS256",
            claims.get("iss") != self.client_email,
            claims.get("aud") != TOKEN_URL,
            set(str(claims.get("scope", "")).split()) != SCOPES,
            not claims.get("iat", 0) - 60 <= now <= claims.get("exp", 0),
        ]
        if any(problems):
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Invalid JWT claims."})
        if claims.get("sub") != self.admin:
            return httpx.Response(
                401, json={"error": "unauthorized_client", "error_description": "Client is unauthorized."}
            )
        access_token = secrets.token_hex(16)
        self._issued.add(access_token)
        return httpx.Response(200, json={"access_token": access_token, "expires_in": 3599, "token_type": "Bearer"})
