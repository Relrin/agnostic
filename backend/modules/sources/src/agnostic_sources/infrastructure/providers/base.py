"""What the git host API clients share: JSON calls with errors people can act on, and paging through lists."""

from __future__ import annotations

import base64
from typing import Any, NoReturn, cast
from urllib.parse import urlsplit, urlunsplit

import httpx

from agnostic_sources.application.ports import ProviderError, Remote

NOT_FOUND = 404
FORBIDDEN = 403
UNAUTHORIZED = 401
UNPROCESSABLE = 422
CONFLICT = 409
ALREADY_OPEN = frozenset({CONFLICT, UNPROCESSABLE})
"""How hosts refuse a second pull request for the same branches (GitHub 422; GitLab, Gitea and Forgejo 409)."""


def already_open(exc: ProviderError) -> bool:
    return exc.extra.get("upstream_status") in ALREADY_OPEN


MAX_PAGES = 20
"""Pages a list call follows at most (2,000 repositories or branches at 100 a page)."""
PER_PAGE = 100


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def remote_for(web_url: str, api_url: str, repo: str, clone_url: str | None, header: str) -> Remote:
    """The repository's https remote with the connection's credentials.

    A clone URL typed for the source gets them only when it's on the connection's own host (its web or API
    address): the token never goes to another server, and an ssh URL has no use for an http header.
    """
    if not clone_url:
        return Remote(f"{web_url.rstrip('/')}/{repo}.git", header=header)
    parts = urlsplit(clone_url)
    hosts = {(urlsplit(url).hostname or "").lower() for url in (web_url, api_url)}
    same_host = parts.scheme in {"https", "http"} and (parts.hostname or "").lower() in hosts
    return Remote(clone_url, header=header if same_host else None)


class Api:
    def __init__(self, client: httpx.AsyncClient, base_url: str, host: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._host = host

    async def headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def _send(
        self, method: str, url: str, *, params: dict[str, str | int] | None = None, json: object = None
    ) -> tuple[httpx.Response, Any]:
        try:
            response = await self._client.request(method, url, params=params, json=json, headers=await self.headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self._host} couldn't be reached: {exc}") from exc
        body: Any = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = response.text[:300]
        return response, body

    def _raise(self, response: httpx.Response, body: object) -> NoReturn:
        raise ProviderError(
            _message(self._host, response.status_code, body), extra={"upstream_status": response.status_code}
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: object = None,
        allow: frozenset[int] = frozenset(),
    ) -> tuple[int, Any]:
        response, body = await self._send(method, f"{self._base}{path}", params=params, json=json)
        if response.is_success or response.status_code in allow:
            return response.status_code, body
        return self._raise(response, body)

    async def json(self, method: str, path: str, **kwargs: Any) -> Any:  # noqa: ANN401
        _, body = await self.request(method, path, **kwargs)
        return body

    async def pages(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        key: str | None = None,
        page_param: str = "per_page",
        max_pages: int = MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """Every item of a list call, up to ``max_pages`` pages.

        Pages follow the ``Link: rel="next"`` header (GitHub, Gitea, Forgejo) or ``X-Next-Page`` (GitLab).
        """
        query: dict[str, str | int] = {page_param: PER_PAGE, **(params or {})}
        url: str | None = f"{self._base}{path}"
        found: list[dict[str, Any]] = []
        for _ in range(max_pages):
            if url is None:
                break
            # No ``params`` when following a ``Link``: httpx would replace the URL's own query with an empty one.
            response, body = await self._send("GET", url, params=query or None)
            if not response.is_success:
                self._raise(response, body)
            found.extend(items(body, key))
            url, query = self._next(response, url, query)
        return found

    def _next(
        self, response: httpx.Response, url: str, query: dict[str, str | int]
    ) -> tuple[str | None, dict[str, str | int]]:
        page = response.headers.get("X-Next-Page", "").strip()
        link = response.links.get("next", {}).get("url")
        if link and _origin(link) == _origin(self._base):
            return link, {}  # the next page's URL carries its own query
        if page.isdigit():
            return url, {**query, "page": int(page)}
        if link:
            # Built from the server's public URL (GitLab's external_url, Gitea's ROOT_URL), which can differ from
            # the address the connection uses. Follow it here, and only within this API: the token never goes to
            # another host, nor anywhere but the next page of the same listing.
            parts = urlsplit(link)
            base = urlsplit(self._base)
            if parts.path.startswith(base.path.rstrip("/") + "/"):
                return urlunsplit((base.scheme, base.netloc, parts.path, parts.query, "")), {}
        return None, query


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower()


def _message(host: str, status: int, body: object) -> str:
    detail = ""
    if isinstance(body, dict):
        data = cast("dict[str, Any]", body)
        detail = str(data.get("message") or data.get("error") or "")
    elif isinstance(body, str):
        detail = body
    if status in {UNAUTHORIZED, FORBIDDEN}:
        prefix = f"{host} refused the connection's credentials"
    elif status == NOT_FOUND:
        prefix = f"{host} doesn't know this repository (or the connection can't see it)"
    else:
        prefix = f"{host} answered HTTP {status}"
    return f"{prefix}: {detail}" if detail else prefix


def items(body: object, key: str | None = None) -> list[dict[str, Any]]:
    if key is not None and isinstance(body, dict):
        body = cast("dict[str, Any]", body).get(key)
    if isinstance(body, list):
        return [cast("dict[str, Any]", item) for item in cast("list[Any]", body) if isinstance(item, dict)]
    return []
