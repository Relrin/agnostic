"""Google Workspace Admin SDK (Directory API, read-only) with a service account and domain-wide delegation.

The service account signs a JWT (RS256) naming the Workspace admin it acts as (``sub``) and exactly the two
read-only directory scopes, exchanges it at Google's token endpoint for an access token (cached until shortly
before it expires), then pages through ``groups``, ``groups/{id}/members`` and ``users``. The token endpoint is
fixed: a ``token_uri`` in the uploaded key file is ignored, so a key file can't point the signed assertion
elsewhere.
"""

from __future__ import annotations

import base64
import time
from typing import Any, cast
from urllib.parse import quote

import httpx
import orjson
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from agnostic_directory.application.ports import GoogleDirectoryError, GoogleGroup, GoogleUser
from agnostic_directory.domain.sync import GOOGLE_SCOPES, GoogleCredentials

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
API_URL = "https://admin.googleapis.com/admin/directory/v1"
JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ASSERTION_TTL = 3600
MAX_PAGES = 1000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def signed_assertion(credentials: GoogleCredentials, *, now: int) -> str:
    """The JWT a service account exchanges for a delegated access token."""
    try:
        key = serialization.load_pem_private_key(credentials.private_key.encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise GoogleDirectoryError("The service account's private key can't be read.") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise GoogleDirectoryError("The service account's private key must be an RSA key.")
    header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
    if credentials.private_key_id:
        header["kid"] = credentials.private_key_id
    claims = {
        "iss": credentials.client_email,
        "sub": credentials.admin_subject,
        "scope": " ".join(GOOGLE_SCOPES),
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + ASSERTION_TTL,
    }
    signing_input = f"{_b64(orjson.dumps(header))}.{_b64(orjson.dumps(claims))}".encode()
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode()}.{_b64(signature)}"


def _problem(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        data = cast("dict[str, Any]", body)
        error = data.get("error")
        if isinstance(error, dict):
            return str(cast("dict[str, Any]", error).get("message") or f"HTTP {response.status_code}")
        return str(data.get("error_description") or error or f"HTTP {response.status_code}")
    return f"HTTP {response.status_code}"


class HttpGoogleDirectory:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, *, timeout: float = 15.0) -> None:
        self._http = httpx.AsyncClient(
            transport=transport, timeout=timeout, headers={"User-Agent": "agnostic-directory/0.1"}
        )
        self._tokens: dict[tuple[str, str, str | None], tuple[str, float]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def groups(self, credentials: GoogleCredentials) -> list[GoogleGroup]:
        items = await self._pages(credentials, "/groups", {"customer": credentials.customer_id}, "groups")
        return [
            GoogleGroup(id=str(item.get("id")), email=str(item.get("email") or ""), name=str(item.get("name") or ""))
            for item in items
            if item.get("id")
        ]

    async def member_emails(self, credentials: GoogleCredentials, group_id: str) -> list[str]:
        items = await self._pages(
            credentials,
            f"/groups/{quote(group_id, safe='')}/members",
            {"includeDerivedMembership": "true"},
            "members",
        )
        return [
            str(item["email"])
            for item in items
            if item.get("email") and item.get("type", "USER") == "USER" and item.get("status", "ACTIVE") == "ACTIVE"
        ]

    async def users(self, credentials: GoogleCredentials) -> list[GoogleUser]:
        items = await self._pages(
            credentials, "/users", {"customer": credentials.customer_id, "projection": "basic"}, "users"
        )
        return [_user(item) for item in items if item.get("primaryEmail")]

    async def user(self, credentials: GoogleCredentials, key: str) -> GoogleUser:
        return _user(await self._get(credentials, f"/users/{quote(key, safe='@')}", {}))

    async def _pages(
        self, credentials: GoogleCredentials, path: str, params: dict[str, str], key: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            query = {**params, "maxResults": "200"}
            if page_token:
                query["pageToken"] = page_token
            data = await self._get(credentials, path, query)
            page = data.get(key)
            if isinstance(page, list):
                items.extend(
                    cast("dict[str, Any]", item) for item in cast("list[object]", page) if isinstance(item, dict)
                )
            next_token = data.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                return items
            page_token = next_token
        raise GoogleDirectoryError(f"Google returned more than {MAX_PAGES} pages for {path}.")

    async def _get(self, credentials: GoogleCredentials, path: str, params: dict[str, str]) -> dict[str, Any]:
        token = await self._token(credentials)
        try:
            response = await self._http.get(
                f"{API_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            raise GoogleDirectoryError(f"Couldn't reach Google: {exc}") from exc
        if response.status_code in {401, 403}:
            self._tokens.pop(self._key(credentials), None)
            raise GoogleDirectoryError(
                f"Google refused the Directory API call ({_problem(response)}). Check the domain-wide delegation "
                "of the service account and that the admin can read the directory."
            )
        if response.status_code == 404:  # noqa: PLR2004
            raise GoogleDirectoryError(f"Google doesn't know {path.rsplit('/', 1)[-1]} ({_problem(response)}).")
        if response.status_code >= 400:  # noqa: PLR2004
            raise GoogleDirectoryError(f"Google answered {response.status_code}: {_problem(response)}")
        body = response.json()
        return cast("dict[str, Any]", body) if isinstance(body, dict) else {}

    async def _token(self, credentials: GoogleCredentials) -> str:
        key = self._key(credentials)
        cached = self._tokens.get(key)
        now = time.time()
        if cached is not None and cached[1] > now + 60:
            return cached[0]
        assertion = signed_assertion(credentials, now=int(now))
        try:
            response = await self._http.post(TOKEN_URL, data={"grant_type": JWT_BEARER, "assertion": assertion})
        except httpx.HTTPError as exc:
            raise GoogleDirectoryError(f"Couldn't reach Google: {exc}") from exc
        if response.status_code != 200:  # noqa: PLR2004
            raise GoogleDirectoryError(f"Google refused the service account: {_problem(response)}")
        body = response.json()
        data = cast("dict[str, Any]", body) if isinstance(body, dict) else {}
        access_token = data.get("access_token")
        if not isinstance(access_token, str):
            raise GoogleDirectoryError("Google's token response had no access token.")
        expires_in = data.get("expires_in", 3600)
        self._tokens[key] = (access_token, now + float(expires_in if isinstance(expires_in, int | float) else 3600))
        return access_token

    @staticmethod
    def _key(credentials: GoogleCredentials) -> tuple[str, str, str | None]:
        return credentials.client_email, credentials.admin_subject, credentials.private_key_id


def _user(item: dict[str, Any]) -> GoogleUser:
    name = item.get("name")
    full_name = cast("dict[str, Any]", name).get("fullName") if isinstance(name, dict) else None
    aliases = item.get("aliases")
    return GoogleUser(
        id=str(item.get("id") or ""),
        primary_email=str(item.get("primaryEmail") or ""),
        name=str(full_name or item.get("primaryEmail") or ""),
        suspended=bool(item.get("suspended")),
        aliases=tuple(str(a) for a in cast("list[object]", aliases)) if isinstance(aliases, list) else (),
    )
