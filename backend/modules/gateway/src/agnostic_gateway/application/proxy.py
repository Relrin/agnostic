"""The gateway: ``ANY /api/v1/instances/{instance}/os/{path}`` → the instance's AgentOS, as the caller.

The caller is the signed-in person, or the service account behind a gateway token.

For each call: match the route policy → pre-check the person's effective scopes (403 with an explanation, audited) →
rate limit → circuit breaker → JWT for (person, instance, scopes) from cache or freshly minted → stream the request
to AgentOS → map AgentOS errors that need context (503, 401) → stream the response back (SSE with heartbeats; small
GETs cached per scope set) → audit (writes and denials always, reads sampled).

Service accounts (``Authorization: Bearer agn_pat_…``) get their scopes from their own bindings. AgentOS rejects JWT
subjects starting with ``sa:``, so their token says ``sub = svc_<name>`` with ``agnostic.principal = sa:<name>``.
Unless the account forwards ``user_id``, a ``user_id`` the caller sends (query string, form or JSON body) is dropped
so runs stay attributed to the account. They can't resolve approvals, even with ``approvals:write``.
"""

from __future__ import annotations

import base64
import hashlib
import random
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode

import httpx
import orjson

from agnostic_access.facade import (
    ADMIN_SCOPE,
    AccessFacade,
    EffectiveAccess,
    PrincipalKind,
    compress,
    satisfies,
    split,
)
from agnostic_agentos_client import InstanceUnreachableError
from agnostic_audit.facade import AuditEntry, AuditLog, Decision, actor_of
from agnostic_gateway.application.ports import RoutePolicyRepository, Upstream
from agnostic_gateway.application.streaming import CircuitBreaker, with_heartbeats
from agnostic_gateway.domain.policies import (
    DEFAULT_POLICIES,
    PolicyTable,
    RoutePolicy,
    merged,
    request_headers,
    response_headers,
    scopes_for_token,
)
from agnostic_instances.facade import AuthMode, Instance, InstancesFacade, InstanceStatus, SubClaimMode
from agnostic_kernel.auth import Principal
from agnostic_kernel.context import current_client, current_request_id
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, access_generation
from agnostic_kernel.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ScopeMissingError,
)
from agnostic_kernel.logging import get_logger
from agnostic_settings.facade import OrgSettingsReader

log = get_logger(__name__)

TABLE_TTL = 60.0
INSTANCE_TTL = 15.0
MAX_CACHED_BODY = 1024 * 1024
TOKEN_REFRESH_MARGIN = 30
SERVICE_ACCOUNT_VIA = "gateway-pat"
SERVICE_ACCOUNT_SUBJECT_PREFIX = "svc_"
USER_ID_FIELD = "user_id"
SERVICE_ACCOUNT_APPROVALS = (
    "Scoped service accounts can't resolve approvals, even with approvals:write: AgentOS hides other callers' "
    "approvals from them (404 under user isolation) and delegated elevation never applies to service accounts. "
    "Someone with approvals:write decides it in the approvals inbox."
)
SERVICE_ACCOUNT_DENIED_ROUTES = frozenset({("POST", "/approvals/{approval_id}/resolve")})
_MULTIPART_USER_ID = re.compile(rb'(?im)^content-disposition:[^\r\n]*[;\s]name="?user_id"?\s*(?:;|$)')


class CapabilityDisabledError(AppError):
    status = 503
    code = "capability_disabled"
    title = "This feature isn't enabled on the instance"


class InstanceAuthFailedError(AppError):
    status = 502
    code = "instance_auth_failed"
    title = "The instance rejected the control plane's credentials"


class GatewayUnreachableError(AppError):
    status = 502
    code = "instance_unreachable"
    title = "The instance didn't answer"


class InstanceDisabledError(ConflictError):
    code = "instance_disabled"
    title = "The instance is disabled"


class GatewayScopeMissingError(ScopeMissingError):
    pass


class ServiceAccountDeniedError(ForbiddenError):
    code = "service_account_denied"
    title = "Service accounts can't do this"


@dataclass(frozen=True, slots=True)
class GatewaySettingsView:
    read_sample_rate: float
    rate_limits: Mapping[str, int]
    heartbeat_seconds: float
    max_body_bytes: int
    max_upload_bytes: int


@dataclass(frozen=True, slots=True)
class ProxyRequest:
    method: str
    path: str
    params: list[tuple[str, str]]
    headers: list[tuple[str, str]]
    body: AsyncIterator[bytes] | None
    scheme: str
    host: str | None


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    status: int
    headers: dict[str, str]
    body: AsyncIterator[bytes]
    close: Callable[[], Awaitable[None]]


class PolicyTableCache:
    """Defaults merged with database overrides, rebuilt at most once a minute per process."""

    def __init__(self) -> None:
        self._table: PolicyTable | None = None
        self._expires = 0.0

    async def get(self, repository: RoutePolicyRepository) -> PolicyTable:
        if self._table is None or self._expires < time.monotonic():
            self._table = PolicyTable(merged(DEFAULT_POLICIES, await repository.overrides()))
            self._expires = time.monotonic() + TABLE_TTL
        return self._table

    def invalidate(self) -> None:
        self._table = None


class InstanceCache:
    """Instance records by id/slug for a few seconds: no database round trip per proxied call."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Instance]] = {}

    async def get(self, ref: str, instances: InstancesFacade) -> Instance | None:
        cached = self._items.get(ref)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        instance = await instances.get(ref)
        if instance is not None:
            expires = time.monotonic() + INSTANCE_TTL
            self._items[ref] = (expires, instance)
            self._items[instance.id] = (expires, instance)
        return instance


def _holds(runtime: frozenset[str], required: str, *, list_filter: bool) -> bool:
    if any(satisfies(held, required) for held in runtime):
        return True
    if list_filter:
        resource, _, action = split(required)
        return any(split(held)[0] == resource and split(held)[2] == action for held in runtime)
    return False


def _digest(values: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(values).encode()).hexdigest()[:20]


class Gateway:
    def __init__(
        self,
        access: AccessFacade,
        instances: InstancesFacade,
        settings: OrgSettingsReader,
        audit: AuditLog,
        store: EphemeralStore,
        upstream: Upstream,
        breaker: CircuitBreaker,
        policies: RoutePolicyRepository,
        table_cache: PolicyTableCache,
        instance_cache: InstanceCache,
        config: GatewaySettingsView,
    ) -> None:
        self._access = access
        self._instances = instances
        self._settings = settings
        self._audit = audit
        self._store = store
        self._upstream = upstream
        self._breaker = breaker
        self._policies = policies
        self._table_cache = table_cache
        self._instance_cache = instance_cache
        self._config = config

    async def handle(  # noqa: C901, PLR0912, PLR0915  (one linear pipeline; each step is a guard clause)
        self, principal: Principal, instance_ref: str, request: ProxyRequest
    ) -> ProxyResponse:
        instance = await self._instance_cache.get(instance_ref, self._instances)
        if instance is None:
            raise NotFoundError(f"There is no instance {instance_ref!r}.")
        if instance.status is InstanceStatus.DISABLED:
            raise InstanceDisabledError(f"{instance.display_name} is disabled. Enable it in Settings › Connection.")

        path = "/" + request.path.lstrip("/")
        table = await self._table_cache.get(self._policies)
        policy, params = table.match(request.method, path)
        if policy.source == "fallback":
            log.warning("gateway.unknown_route", method=request.method, path=path, instance=instance.id)
        required = list(policy.required(params))
        if instance.auth_mode in {AuthMode.NONE, AuthMode.SECURITY_KEY}:
            # No per-user permissions on such runtimes: only Instance admins (06 §4).
            required = [ADMIN_SCOPE]

        kind: PrincipalKind = "service_account" if principal.kind == "service_account" else "user"
        access = await self._access.access_for(kind, principal.id, instance.id)
        runtime = access.runtime_scopes()
        missing = [scope for scope in required if not _holds(runtime, scope, list_filter=policy.list_filter)]
        route = f"{request.method} {policy.pattern}"
        if principal.kind == "service_account" and (policy.method, policy.pattern) in SERVICE_ACCOUNT_DENIED_ROUTES:
            await deny_service_account(
                self._audit, principal, instance, method=request.method, path=path, route=route, required=required
            )
        if missing:
            await self._deny(principal, instance, policy, route, path, required, missing)
        if principal.kind == "service_account" and not principal.forwards_user_id:
            request = await without_user_id(request)

        await self._rate_limit(principal, instance, policy)
        retry_after = self._breaker.retry_after(instance.id)
        if retry_after is not None:
            raise GatewayUnreachableError(
                f"{instance.display_name} failed several times in a row; retrying in {retry_after:.0f} s.",
                extra={"retry_after": round(retry_after)},
            )

        credentials, scope_key = await self._credentials(principal, instance, access, policy)
        cache_key = await self._cache_key(instance, policy, request, scope_key) if policy.cache_ttl_s else None
        if cache_key is not None:
            hit = await self._store.get(cache_key)
            if hit is not None:
                await self._maybe_audit(principal, instance, policy, path, required, 200)
                return _cached_response(hit, instance)

        headers = {
            **request_headers(request.headers),
            **credentials,
            "X-Request-Id": current_request_id() or "",
            "X-Forwarded-Proto": request.scheme,
        }
        client_ip = current_client().ip
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
        if request.host:
            headers["X-Forwarded-Host"] = request.host
        try:
            response = await self._upstream.send(
                instance, request.method, path, params=request.params, headers=headers, body=request.body
            )
        except InstanceUnreachableError as exc:
            self._breaker.failure(instance.id)
            raise GatewayUnreachableError(f"{instance.display_name} didn't answer: {exc}") from exc
        self._breaker.success(instance.id)

        if response.status_code in {401, 503}:
            await self._raise_upstream_problem(instance, response)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:  # noqa: PLR2004
            _ = await self._store.incr(f"gw:gen:{instance.id}", ttl=86400)
        await self._maybe_audit(principal, instance, policy, path, required, response.status_code)
        return await self._respond(instance, response, cache_key, policy)

    async def _deny(
        self,
        principal: Principal,
        instance: Instance,
        policy: RoutePolicy,
        route: str,
        path: str,
        required: list[str],
        missing: list[str],
    ) -> None:
        explanation = await self._access.explain(principal, missing[0], instance, action_label=route)
        text = explanation.text
        if instance.auth_mode in {AuthMode.NONE, AuthMode.SECURITY_KEY} and missing == [ADMIN_SCOPE]:
            text = (
                f"{instance.display_name} has no per-user permissions ({instance.auth_mode.value}); "
                "only Instance admins can use it through the gateway. " + text
            )
        await self._record(principal, instance, policy, path, required, 403, "denied", missing, reason=text)
        raise GatewayScopeMissingError(
            text,
            extra={
                "required_scopes": required,
                "missing_scopes": missing,
                "explanation": text,
                "instance_id": instance.id,
                "route": route,
                "alternatives": [
                    {"kind": item.kind, "label": item.label, "role_name": item.role_name}
                    for item in explanation.alternatives
                ],
            },
        )

    async def _rate_limit(self, principal: Principal, instance: Instance, policy: RoutePolicy) -> None:
        limit = self._config.rate_limits.get(policy.rate_bucket)
        if not limit:
            return
        window = int(time.time() // 60)
        key = f"rl:gw:{principal.id}:{instance.id}:{policy.rate_bucket}:{window}"
        if await self._store.incr(key, ttl=70) > limit:
            raise RateLimitedError(
                f"More than {limit} {policy.rate_bucket} calls a minute to {instance.display_name}. Slow down.",
                extra={"retry_after": 60 - int(time.time()) % 60},
            )

    async def _credentials(
        self, principal: Principal, instance: Instance, access: EffectiveAccess, policy: RoutePolicy
    ) -> tuple[dict[str, str], str]:
        """Headers for AgentOS, and a digest of what they grant (the response-cache key part)."""
        if instance.auth_mode is AuthMode.NONE:
            return {}, "none"
        if instance.auth_mode is AuthMode.SECURITY_KEY:
            key = await self._instances.security_key(instance)
            return ({"Authorization": f"Bearer {key}"} if key else {}), "security-key"
        scopes, trimmed = scopes_for_token(compress(access.runtime_scopes()), policy.family)
        if trimmed:
            log.warning("gateway.scopes_trimmed", user=principal.id, instance=instance.id, family=policy.family)
        via = "gateway"
        extra: dict[str, Any] | None = None
        if principal.kind == "service_account":
            # AgentOS reserves ``sa:`` subjects: the run's user is ``svc_<name>``, the claim names the account.
            subject = SERVICE_ACCOUNT_SUBJECT_PREFIX + principal.display_name.removeprefix("sa:")
            via = SERVICE_ACCOUNT_VIA
            extra = {
                "agnostic": {
                    "via": via,
                    "instance": instance.id,
                    "name": principal.display_name,
                    "principal": principal.display_name,
                }
            }
        elif instance.sub_claim_mode is SubClaimMode.EMAIL and principal.email:
            subject = principal.email
        else:
            subject = principal.id
        generation = await access_generation(self._store)
        scope_key = _digest(scopes)
        key = f"jwt:{generation}:{principal.id}:{instance.id}:{_digest([subject, *scopes])}"
        cached = await self._store.get(key)
        if cached is not None:
            return {"Authorization": f"Bearer {cached.decode()}"}, scope_key
        minted = await self._instances.mint(
            instance, subject=subject, scopes=scopes, name=principal.display_name, via=via, extra=extra
        )
        ttl = (minted.expires_at - utcnow()).total_seconds() - TOKEN_REFRESH_MARGIN
        if ttl > 0:
            await self._store.set(key, minted.token.encode(), ttl=ttl)
        return {"Authorization": f"Bearer {minted.token}"}, scope_key

    async def _cache_key(
        self, instance: Instance, policy: RoutePolicy, request: ProxyRequest, scope_key: str
    ) -> str | None:
        if request.method != "GET":
            return None
        generation = (await self._store.get(f"gw:gen:{instance.id}") or b"0").decode()
        query = "&".join(f"{k}={v}" for k, v in sorted(request.params))
        # Keyed by the scope set, so people never see responses their scopes don't allow.
        return f"gw:{generation}:{instance.id}:{policy.pattern}:{request.path}?{query}:{scope_key}"

    async def _raise_upstream_problem(self, instance: Instance, response: httpx.Response) -> None:
        body = (await response.aread())[:2000].decode(errors="replace")
        await response.aclose()
        detail = body
        try:
            parsed: Any = orjson.loads(body)
            if isinstance(parsed, dict) and "detail" in parsed:
                detail = str(parsed["detail"])  # pyright: ignore[reportUnknownArgumentType]
        except orjson.JSONDecodeError:
            pass
        if response.status_code == 503:  # noqa: PLR2004
            raise CapabilityDisabledError(
                f"{instance.display_name}: {detail or 'this feature is not enabled on the runtime.'}",
                extra={"instance_id": instance.id, "upstream_status": 503},
            )
        raise InstanceAuthFailedError(
            f"{instance.display_name} rejected the token the control plane minted ({detail}). Its public key is "
            "probably missing or outdated: run Test connection in Settings › Connection.",
            extra={"instance_id": instance.id, "upstream_status": 401},
        )

    async def _maybe_audit(
        self,
        principal: Principal,
        instance: Instance,
        policy: RoutePolicy,
        path: str,
        required: list[str],
        status: int,
    ) -> None:
        if policy.audit_level == "none":
            return
        is_read = policy.rate_bucket == "read" and policy.audit_level == "decision"
        if is_read:
            settings = await self._settings.get()
            if not settings.audit_log_all_reads and random.random() >= self._config.read_sample_rate:  # noqa: S311
                return
        await self._record(principal, instance, policy, path, required, status, "allowed", [])

    async def _record(
        self,
        principal: Principal,
        instance: Instance,
        policy: RoutePolicy,
        path: str,
        required: list[str],
        status: int,
        decision: Decision,
        missing: list[str],
        *,
        reason: str | None = None,
    ) -> None:
        method = policy.method
        _ = await self._audit.record_now(
            AuditEntry(
                action="gateway.request" if decision == "allowed" else "gateway.denied",
                actor=actor_of(principal),
                resource_kind="route",
                resource_id=f"{method} {policy.pattern}",
                resource_display=f"{method} {path}",
                instance_id=instance.id,
                decision=decision,
                scope_checked=required[0] if required else None,
                missing_scopes=tuple(missing),
                denial_reason=reason,
                response_status=status,
                via="gateway",
                fields={"route": f"{method} {path}", "instance": instance.display_name, "scope": ", ".join(missing)},
            )
        )

    async def _respond(
        self, instance: Instance, response: httpx.Response, cache_key: str | None, policy: RoutePolicy
    ) -> ProxyResponse:
        content_type = response.headers.get("content-type", "")
        streaming = content_type.startswith("text/event-stream")
        headers = response_headers(response.headers.multi_items(), streaming=streaming)
        headers["X-Agnostic-Instance"] = instance.slug
        if streaming:
            headers["Cache-Control"] = "no-cache"
            headers["X-Accel-Buffering"] = "no"
            body = with_heartbeats(response.aiter_raw(), self._config.heartbeat_seconds)
            return ProxyResponse(response.status_code, headers, body, response.aclose)

        if cache_key is not None and response.status_code == 200:  # noqa: PLR2004
            content = await response.aread()
            await response.aclose()
            if len(content) <= MAX_CACHED_BODY:
                entry = {
                    "status": 200,
                    "headers": headers,
                    "body": base64.b64encode(content).decode(),
                }
                await self._store.set(cache_key, orjson.dumps(entry), ttl=policy.cache_ttl_s)
            return ProxyResponse(200, headers, _once(content), _noop)
        return ProxyResponse(response.status_code, headers, response.aiter_raw(), response.aclose)


async def _once(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def deny_service_account(
    audit: AuditLog,
    principal: Principal,
    instance: Instance,
    *,
    method: str,
    path: str,
    route: str,
    required: Sequence[str],
) -> None:
    """Record and refuse an approval resolution by a service account (passthrough or typed decision)."""
    text = SERVICE_ACCOUNT_APPROVALS
    _ = await audit.record_now(
        AuditEntry(
            action="gateway.denied",
            actor=actor_of(principal),
            resource_kind="route",
            resource_id=route,
            resource_display=f"{method} {path}",
            instance_id=instance.id,
            decision="denied",
            scope_checked=required[0] if required else None,
            response_status=403,
            via="gateway",
            fields={"route": f"{method} {path}", "instance": instance.display_name, "scope": "", "reason": text},
            summary=f"{principal.display_name} was denied {method} {path} on {instance.display_name}: {text}",
            denial_reason=text,
        )
    )
    raise ServiceAccountDeniedError(
        text,
        extra={
            "required_scopes": list(required),
            "missing_scopes": [],
            "explanation": text,
            "instance_id": instance.id,
            "route": route,
            "alternatives": [],
        },
    )


async def without_user_id(request: ProxyRequest) -> ProxyRequest:
    """Drop ``user_id`` from the query string and from form, multipart or JSON bodies (buffered)."""
    params = [(key, value) for key, value in request.params if key != USER_ID_FIELD]
    if request.body is None or request.method in {"GET", "HEAD", "OPTIONS"}:
        return replace(request, params=params)
    content_type = next((value for name, value in request.headers if name.lower() == "content-type"), "")
    media = content_type.split(";", 1)[0].strip().lower()
    if media not in {"application/x-www-form-urlencoded", "application/json", "multipart/form-data"}:
        return replace(request, params=params)
    raw = b"".join([chunk async for chunk in request.body])
    stripped = _strip_user_id(media, content_type, raw)
    headers = [(name, value) for name, value in request.headers if name.lower() != "content-length"]
    headers.append(("content-length", str(len(stripped))))
    return replace(request, params=params, headers=headers, body=_once(stripped))


def _strip_user_id(media: str, content_type: str, raw: bytes) -> bytes:
    if media == "application/x-www-form-urlencoded":
        return _strip_form(raw)
    if media == "application/json":
        return _strip_json(raw)
    return _strip_multipart(content_type, raw)


def _strip_form(raw: bytes) -> bytes:
    pairs = parse_qsl(raw.decode(errors="replace"), keep_blank_values=True)
    if all(key != USER_ID_FIELD for key, _ in pairs):
        return raw
    return urlencode([(key, value) for key, value in pairs if key != USER_ID_FIELD]).encode()


def _strip_json(raw: bytes) -> bytes:
    try:
        parsed: Any = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return raw
    if isinstance(parsed, dict) and USER_ID_FIELD in parsed:
        fields = cast("dict[str, Any]", parsed)
        return orjson.dumps({key: value for key, value in fields.items() if key != USER_ID_FIELD})
    return raw


def _strip_multipart(content_type: str, raw: bytes) -> bytes:
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if match is None:
        return raw
    delimiter = b"--" + match.group(1).encode()
    pieces = raw.split(delimiter)
    kept = [pieces[0]] + [p for p in pieces[1:] if not _MULTIPART_USER_ID.search(p.split(b"\r\n\r\n", 1)[0])]
    return delimiter.join(kept) if len(kept) != len(pieces) else raw


async def _noop() -> None:
    return None


def _cached_response(raw: bytes, instance: Instance) -> ProxyResponse:
    entry = orjson.loads(raw)
    headers = {str(k): str(v) for k, v in entry["headers"].items()}
    headers["X-Agnostic-Instance"] = instance.slug
    headers["X-Agnostic-Cache"] = "hit"
    return ProxyResponse(int(entry["status"]), headers, _once(base64.b64decode(entry["body"])), _noop)
