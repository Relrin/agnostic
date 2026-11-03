"""Service accounts: create, list, issue/rotate/revoke tokens, delete.

An account's grants are access bindings (``principal_kind = service_account``, one per instance) holding the
role and/or the extra scopes, so the gateway's JWT minting and the explain engine reuse the access engine; the
account row keeps what was declared. Native tokens are provisioned per instance through AgentOS
``/service-accounts`` as the control plane; gateway tokens are generated here and only their hash is stored.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from agnostic_access.facade import AccessFacade, AccessRole, compress
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import AgentOSError, Instance, InstancesFacade
from agnostic_kernel.auth import SYSTEM_PRINCIPAL, Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import AppError, ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger
from agnostic_service_accounts.application.ports import RecentAuthentication, ServiceAccountRepository
from agnostic_service_accounts.application.tokens import TokenHashing
from agnostic_service_accounts.domain.accounts import (
    ACCOUNT_ID_PREFIX,
    DEFAULT_EXPIRY,
    GATEWAY_TOKEN_ID_PREFIX,
    NATIVE_TOKEN_ID_PREFIX,
    GatewayToken,
    InvalidServiceAccountError,
    NativeToken,
    ServiceAccount,
    TokenKind,
    check_name,
    cli_command,
    curl_sample,
    display_prefix,
    expires_at,
    is_privileged,
    isolation_note,
    new_gateway_token,
    principal_of,
    sample_agent,
    source_label,
)

log = get_logger(__name__)

MANAGE = "service_accounts:manage"
READ = "org:read"
PRIVILEGED_CREATED = "service_accounts.privileged_created"
"""Domain event: an account with privileged scopes was created (notifications tell the Owners)."""
MAX_NATIVE_DAYS = 3650
POLL_PAGE_SIZE = 100
POLL_MAX_PAGES = 50


class PrivilegedConfirmationRequiredError(ValidationFailedError):
    code = "privileged_confirmation_required"
    title = "Privileged scopes need an explicit confirmation"


class NativeProvisioningError(AppError):
    status = 502
    code = "native_token_failed"
    title = "The instance refused to create or revoke the native token"


@dataclass(frozen=True, slots=True)
class NewServiceAccount:
    name: str
    instances: Sequence[str]
    """Instance ids or slugs."""
    description: str = ""
    role_id: str | None = None
    scopes: Sequence[str] = ()
    expires_in: str = DEFAULT_EXPIRY
    kinds: Sequence[TokenKind] = ("native",)
    forwards_user_id: bool = False
    confirm_privileged: bool = False
    created_by_email: str | None = None
    """Who the account is recorded as created by when the CLI creates it (the system acts)."""


@dataclass(frozen=True, slots=True)
class ScopeItem:
    scope: str
    source: str
    """``role:<name>`` or ``custom``."""
    privileged: bool


@dataclass(frozen=True, slots=True)
class AccountView:
    account: ServiceAccount
    role: AccessRole | None
    instances: tuple[Instance, ...]
    native_tokens: tuple[NativeToken, ...]
    gateway_tokens: tuple[GatewayToken, ...]
    now: datetime

    @property
    def role_name(self) -> str | None:
        return self.role.name if self.role else None

    @property
    def scope_items(self) -> tuple[ScopeItem, ...]:
        items: dict[str, ScopeItem] = {}
        if self.role is not None:
            for scope in sorted(self.role.scopes()):
                items[scope] = ScopeItem(scope, f"role:{self.role.name}", is_privileged(scope))
        for scope in self.account.scopes:
            items.setdefault(scope, ScopeItem(scope, "custom", is_privileged(scope)))
        return tuple(items.values())

    @property
    def all_scopes(self) -> tuple[str, ...]:
        return tuple(item.scope for item in self.scope_items)

    @property
    def privileged(self) -> bool:
        return any(item.privileged for item in self.scope_items)

    @property
    def last_used_at(self) -> datetime | None:
        used = [token.last_used_at for token in self.native_tokens if token.last_used_at is not None]
        used.extend(token.last_used_at for token in self.gateway_tokens if token.last_used_at is not None)
        return max(used, default=None)

    @property
    def source_label(self) -> str:
        return source_label(self.account.scope_source, self.role_name, len(self.account.scopes))

    @property
    def isolation_note(self) -> str:
        return isolation_note(self.account, self.all_scopes)

    @property
    def kinds(self) -> tuple[TokenKind, ...]:
        kinds: list[TokenKind] = []
        if self.native_tokens:
            kinds.append("native")
        if self.gateway_tokens:
            kinds.append("gateway")
        return tuple(kinds) or ("native",)

    def cli_command(self) -> str:
        account = self.account
        return cli_command(
            account.name,
            instances=[instance.slug for instance in self.instances],
            role=self.role.slug if self.role else None,
            scopes=list(account.scopes),
            expires_in=_expires_in(account),
            kinds=list(self.kinds),
            forwards_user_id=account.forwards_user_id,
            privileged=self.privileged,
        )


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A token shown once: right after it was created."""

    id: str
    kind: TokenKind
    token: str
    prefix: str
    instance: Instance | None
    expires_at: datetime | None
    curl: str


@dataclass(frozen=True, slots=True)
class Created:
    view: AccountView
    tokens: tuple[IssuedToken, ...]


@dataclass(frozen=True, slots=True)
class TokenIssued:
    view: AccountView
    token: IssuedToken
    replaced_id: str | None
    """The token this one replaced: revoked (native) or valid until ``grace_until`` (gateway)."""
    grace_until: datetime | None


@dataclass(frozen=True, slots=True)
class Preview:
    principal: str
    privileged_scopes: tuple[str, ...]
    expires_at: datetime | None
    cli_command: str
    problems: tuple[str, ...] = field(default_factory=tuple[str, ...])


def _expires_in(account: ServiceAccount) -> str:
    if account.expires_at is None:
        return "never"
    days = (account.expires_at - account.created_at).days
    return min(("30d", "90d", "365d"), key=lambda choice: abs(int(choice[:-1]) - days))


def _time(value: object) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


class ServiceAccounts:
    def __init__(
        self,
        accounts: ServiceAccountRepository,
        access: AccessFacade,
        instances: InstancesFacade,
        authorizer: Authorizer,
        audit: AuditLog,
        events: DomainEvents,
        recent: RecentAuthentication,
        identity: IdentityFacade,
        hashing: TokenHashing,
        store: EphemeralStore,
        public_url: str,
    ) -> None:
        self._accounts = accounts
        self._access = access
        self._instances = instances
        self._authorizer = authorizer
        self._audit = audit
        self._events = events
        self._recent = recent
        self._identity = identity
        self._hashing = hashing
        self._store = store
        self._public_url = public_url.rstrip("/")

    # ------------------------------------------------------------------ reads

    async def list(self, principal: Principal) -> list[AccountView]:
        _ = await self._authorizer.require(principal, READ)
        accounts = await self._accounts.list()
        return await self._views(accounts)

    async def get(self, principal: Principal, ref: str) -> AccountView:
        _ = await self._authorizer.require(principal, READ)
        return (await self._views([await self._account(ref)]))[0]

    async def _account(self, ref: str) -> ServiceAccount:
        account = await self._accounts.get(ref) if ref.startswith(f"{ACCOUNT_ID_PREFIX}_") else None
        if account is None:
            account = await self._accounts.by_name(ref.removeprefix("sa:"))
        if account is None or account.deleted:
            raise NotFoundError(f"There is no service account {ref!r}.")
        return account

    async def _views(self, accounts: Sequence[ServiceAccount]) -> list[AccountView]:
        ids = [account.id for account in accounts]
        natives = await self._accounts.native_tokens(ids)
        gateway = await self._accounts.gateway_tokens(ids)
        instances = {instance.id: instance for instance in await self._instances.list()}
        roles: dict[str, AccessRole | None] = {}
        now = utcnow()
        views: list[AccountView] = []
        for account in accounts:
            if account.role_id and account.role_id not in roles:
                roles[account.role_id] = await self._access.role(account.role_id)
            views.append(
                AccountView(
                    account=account,
                    role=roles.get(account.role_id) if account.role_id else None,
                    instances=tuple(instances[i] for i in account.instance_ids if i in instances),
                    native_tokens=tuple(t for t in natives if t.account_id == account.id),
                    gateway_tokens=tuple(t for t in gateway if t.account_id == account.id),
                    now=now,
                )
            )
        return views

    # ------------------------------------------------------------------ create

    async def preview(self, principal: Principal, request: NewServiceAccount) -> Preview:
        """What creating would do (principal, privileged scopes, CLI command), without side effects."""
        _ = await self._authorizer.require(principal, READ)
        problems: list[str] = []
        try:
            name = check_name(request.name)
        except InvalidServiceAccountError as exc:
            problems.append(str(exc))
            name = request.name.strip()
        try:
            role = await self._role(request.role_id)
        except ValidationFailedError:
            role = None
        if request.role_id and role is None:
            problems.append(f"There is no access role {request.role_id!r}.")
        unknown = [scope for scope in request.scopes if not self._access.known_scope(scope)]
        if unknown:
            problems.append(f"Unknown scopes: {', '.join(unknown)}.")
        scopes = set(request.scopes) | (set(role.scopes()) if role else set[str]())
        privileged = tuple(sorted(scope for scope in scopes if is_privileged(scope)))
        try:
            until = expires_at(request.expires_in, utcnow())
        except InvalidServiceAccountError as exc:
            problems.append(str(exc))
            until = None
        slugs: list[str] = []
        for ref in request.instances:
            instance = await self._instances.get(ref)
            slugs.append(instance.slug if instance else ref)
        return Preview(
            principal=principal_of(name),
            privileged_scopes=privileged,
            expires_at=until,
            cli_command=cli_command(
                name,
                instances=slugs,
                role=role.slug if role else request.role_id,
                scopes=list(request.scopes),
                expires_in=request.expires_in,
                kinds=list(request.kinds),
                forwards_user_id=request.forwards_user_id,
                privileged=bool(privileged),
            ),
            problems=tuple(problems),
        )

    async def create(  # noqa: C901, PLR0912, PLR0915  (validate, bind, provision, audit, announce)
        self, principal: Principal, request: NewServiceAccount
    ) -> Created:
        _ = await self._authorizer.require(principal, MANAGE)
        try:
            name = check_name(request.name)
            until = expires_at(request.expires_in, utcnow())
        except InvalidServiceAccountError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if await self._accounts.by_name(name) is not None:
            raise ConflictError(f"There already is a service account named {name}.")
        kinds = tuple(dict.fromkeys(request.kinds))
        if not kinds or any(kind not in {"native", "gateway"} for kind in kinds):
            raise ValidationFailedError("Pick the token kinds: native, gateway or both.")
        instances = await self._resolve_instances(request.instances)
        role = await self._role(request.role_id)
        extras = tuple(sorted(set(request.scopes)))
        if role is None and not extras:
            raise ValidationFailedError("Give the service account an access role or at least one scope.")
        unknown = [scope for scope in extras if not self._access.known_scope(scope)]
        if unknown:
            raise ValidationFailedError(f"Unknown scopes: {', '.join(unknown)}.")
        declared = set(extras) | (set(role.scopes()) if role else set[str]())
        privileged = sorted(scope for scope in declared if is_privileged(scope))
        if privileged:
            await self._confirm_privileged(principal, privileged, confirmed=request.confirm_privileged)
        creator_id, creator_name = await self._creator(principal, request.created_by_email)

        now = utcnow()
        account = ServiceAccount(
            id=new_id(ACCOUNT_ID_PREFIX),
            name=name,
            description=request.description.strip(),
            scope_source="role" if role else "custom",
            role_id=role.id if role else None,
            scopes=extras,
            instance_ids=tuple(instance.id for instance in instances),
            forwards_user_id=request.forwards_user_id,
            created_by=creator_id,
            created_by_name=creator_name,
            created_at=now,
            expires_at=until,
        )
        # Native tokens first: no database transaction stays open while the instances answer.
        issued: list[IssuedToken] = []
        natives: list[NativeToken] = []
        try:
            if "native" in kinds:
                for instance in instances:
                    native, token = await self._provision(account, instance, role)
                    natives.append(native)
                    issued.append(self._issued_native(native, token, instance))
            await self._accounts.add(account)
            for instance in instances:
                _ = await self._access.bind_service_account(
                    principal,
                    account.id,
                    instance_id=instance.id,
                    role_id=account.role_id,
                    scopes=extras,
                    expires_at=until,
                )
            for native in natives:
                await self._accounts.add_native(native)
        except BaseException:
            await self._accounts.rollback()
            for native in natives:
                _ = await self._revoke_upstream(native, quiet=True)
            raise
        if "gateway" in kinds:
            gateway, token = self._new_gateway(account, now)
            await self._accounts.add_gateway(gateway)
            issued.append(self._issued_gateway(gateway, token, account, instances))

        where = ", ".join(instance.display_name for instance in instances)
        lines = [{"op": "add", "text": f"{self._grant_label(role, extras)} on {where}"}]
        if privileged:
            lines.append({"op": "note", "text": f"Privileged: {', '.join(privileged)}"})
        _ = await self._audit.record(
            AuditEntry(
                action="service_accounts.create",
                actor=actor_of(principal),
                resource_kind="service_account",
                resource_id=account.id,
                resource_display=account.principal,
                fields={
                    "account": account.principal,
                    "grant": self._grant_label(role, extras),
                    "instances": where,
                    "kinds": " + ".join(kinds),
                    "privileged": "yes" if privileged else "no",
                    "privileged_scopes": ", ".join(privileged),
                    "created_by": creator_name,
                },
                diff={
                    "title": "Service account",
                    "lines": lines,
                    "role_id": account.role_id,
                    "scopes": list(extras),
                    "privileged": bool(privileged),
                },
            )
        )
        for item in issued:
            await self._audit_token(principal, "tokens.create", account, item.kind, item.prefix, item.instance)
        await self._accounts.commit()
        await bump_access_generation(self._store)
        if privileged:
            await self._events.publish(
                PRIVILEGED_CREATED,
                {
                    "service_account_id": account.id,
                    "name": account.name,
                    "principal": account.principal,
                    "scopes": sorted(declared),
                    "privileged_scopes": privileged,
                    "instances": [instance.display_name for instance in instances],
                    "created_by": creator_id,
                    "created_by_name": creator_name,
                },
            )
        view = (await self._views([account]))[0]
        return Created(view=view, tokens=tuple(issued))

    async def _resolve_instances(self, refs: Sequence[str]) -> list[Instance]:
        if not refs:
            raise ValidationFailedError("Pick at least one instance.")
        found: dict[str, Instance] = {}
        for ref in refs:
            instance = await self._instances.get(ref)
            if instance is None:
                raise ValidationFailedError(f"There is no instance {ref!r}.")
            found[instance.id] = instance
        return list(found.values())

    async def _role(self, role_id: str | None) -> AccessRole | None:
        if not role_id:
            return None
        # An id, or a slug (built-in ids are ``rol_<slug with underscores>``).
        role = await self._access.role(role_id) or await self._access.role(role_id.replace("-", "_"))
        if role is None:
            raise ValidationFailedError(f"There is no access role {role_id!r}.")
        return role

    async def _confirm_privileged(self, principal: Principal, privileged: Sequence[str], *, confirmed: bool) -> None:
        if not confirmed:
            what = "is a privileged scope" if len(privileged) == 1 else "are privileged scopes"
            raise PrivilegedConfirmationRequiredError(
                f"{', '.join(privileged)} {what}: confirm to grant them. Owners are notified and the grant is flagged "
                "in the audit log.",
                extra={"privileged_scopes": list(privileged)},
            )
        if principal.kind != "system":
            await self._recent.require(principal)

    async def _creator(self, principal: Principal, email: str | None) -> tuple[str, str]:
        if email:
            user = await self._identity.find_user_by_email(email)
            if user is None:
                raise ValidationFailedError(f"There is no account with the email {email}.")
            return user.id, user.display_name
        return principal.id, principal.display_name

    @staticmethod
    def _grant_label(role: AccessRole | None, extras: Sequence[str]) -> str:
        if role is None:
            return ", ".join(extras)
        return role.name + (f" + {', '.join(extras)}" if extras else "")

    def _native_scopes(self, account: ServiceAccount, instance: Instance, role: AccessRole | None) -> list[str]:
        scopes = set(account.scopes)
        if role is not None and role.bindable_on(instance.id):
            scopes |= set(role.scopes())
        return compress(scope for scope in scopes if not self._access.is_control_plane(scope))

    async def _provision(
        self, account: ServiceAccount, instance: Instance, role: AccessRole | None
    ) -> tuple[NativeToken, str]:
        scopes = self._native_scopes(account, instance, role)
        if not scopes:
            raise ValidationFailedError(
                f"{account.principal} has no AgentOS scopes on {instance.display_name}, so a native token there "
                "would do nothing. Add scopes, or pick only the gateway token."
            )
        now = utcnow()
        body: dict[str, Any] = {"name": account.name, "scopes": [{"scope": s, "effect": "allow"} for s in scopes]}
        if account.expires_at is None:
            body["never_expires"] = True
        else:
            days = math.ceil((account.expires_at - now).total_seconds() / 86400)
            body["expires_in_days"] = max(1, min(MAX_NATIVE_DAYS, days))
        if any(is_privileged(scope) for scope in scopes):
            body["allow_privileged_scopes"] = True
        try:
            raw = await self._instances.system_call(instance, "POST", "/service-accounts", json=body)
        except AgentOSError as exc:
            if exc.status == 409:  # noqa: PLR2004
                raise ConflictError(
                    f"{instance.display_name} already has an active service account named {account.name} "
                    "(created outside Agnostic?). Revoke it there or pick another name."
                ) from exc
            raise NativeProvisioningError(
                f"{instance.display_name} didn't create the native token: {exc.body or exc}",
                extra={"instance_id": instance.id, "upstream_status": exc.status},
            ) from exc
        if not isinstance(raw, dict) or not isinstance(cast("dict[str, Any]", raw).get("token"), str):
            raise NativeProvisioningError(f"{instance.display_name} answered without a token.")
        created = cast("dict[str, Any]", raw)
        token = str(created["token"])
        native = NativeToken(
            id=new_id(NATIVE_TOKEN_ID_PREFIX),
            account_id=account.id,
            instance_id=instance.id,
            agentos_sa_id=str(created.get("id") or ""),
            token_prefix=str(created.get("token_prefix") or token[:13]),
            status="active",
            scopes=tuple(scopes),
            created_at=_time(created.get("created_at")) or now,
            expires_at=_time(created.get("expires_at")) or account.expires_at,
        )
        return native, token

    async def _revoke_upstream(self, native: NativeToken, *, quiet: bool = False) -> bool:
        """Revoke the token on its instance; ``False`` when that failed (``quiet``) — otherwise it raises."""
        instance = await self._instances.get(native.instance_id)
        if instance is None or not native.agentos_sa_id:
            return True
        try:
            _ = await self._instances.system_call(instance, "DELETE", f"/service-accounts/{native.agentos_sa_id}")
        except AgentOSError as exc:
            if exc.status == 404:  # noqa: PLR2004
                return True
            if quiet:
                log.warning("service_accounts.native_revoke_failed", instance=instance.id, error=str(exc))
                return False
            raise NativeProvisioningError(
                f"{instance.display_name} didn't revoke {native.token_prefix}…: {exc.body or exc}. Try again.",
                extra={"instance_id": instance.id, "upstream_status": exc.status},
            ) from exc
        return True

    def _new_gateway(self, account: ServiceAccount, now: datetime) -> tuple[GatewayToken, str]:
        token = new_gateway_token()
        return (
            GatewayToken(
                id=new_id(GATEWAY_TOKEN_ID_PREFIX),
                account_id=account.id,
                prefix=display_prefix(token),
                token_hash=self._hashing.hash(token),
                status="active",
                created_at=now,
            ),
            token,
        )

    def _issued_native(self, native: NativeToken, token: str, instance: Instance) -> IssuedToken:
        return IssuedToken(
            id=native.id,
            kind="native",
            token=token,
            prefix=native.token_prefix,
            instance=instance,
            expires_at=native.expires_at,
            curl=curl_sample(instance.endpoint_url, variable="AGNO_PAT", agent_id=sample_agent(native.scopes)),
        )

    def _issued_gateway(
        self, gateway: GatewayToken, token: str, account: ServiceAccount, instances: Sequence[Instance]
    ) -> IssuedToken:
        slug = instances[0].slug if instances else "<instance>"
        return IssuedToken(
            id=gateway.id,
            kind="gateway",
            token=token,
            prefix=gateway.prefix,
            instance=None,
            expires_at=account.expires_at,
            curl=curl_sample(
                f"{self._public_url}/api/v1/instances/{slug}/os",
                variable="AGN_PAT",
                agent_id=sample_agent(account.scopes),
            ),
        )

    # ------------------------------------------------------------------ tokens

    async def issue_token(
        self, principal: Principal, ref: str, kind: TokenKind, instance_ref: str | None
    ) -> TokenIssued:
        """Issue a token, or rotate the current one of that kind (and instance)."""
        _ = await self._authorizer.require(principal, MANAGE)
        account = await self._account(ref)
        now = utcnow()
        if not account.usable(now):
            raise ConflictError(f"{account.principal} has expired; create a new service account.")
        view = (await self._views([account]))[0]
        if view.privileged and principal.kind != "system":
            await self._recent.require(principal)
        if kind == "gateway":
            current = [token for token in view.gateway_tokens if token.valid(now) and not token.rotated]
            grace_until: datetime | None = None
            for token in current:
                rotated = token.rotate_out(now)
                grace_until = rotated.grace_until
                await self._accounts.save_gateway(rotated)
            gateway, plaintext = self._new_gateway(account, now)
            await self._accounts.add_gateway(gateway)
            issued = self._issued_gateway(gateway, plaintext, account, view.instances)
            replaced = current[0].id if current else None
        elif kind == "native":
            instance = await self._token_instance(account, instance_ref)
            current_native = [t for t in view.native_tokens if t.instance_id == instance.id and t.active]
            for token in current_native:
                _ = await self._revoke_upstream(token)
                await self._accounts.save_native(token.revoke(now))
            if current_native:
                await self._accounts.commit()  # revoked on the instance: keep that even if recreating fails
            native, plaintext = await self._provision(account, instance, view.role)
            await self._accounts.add_native(native)
            issued = self._issued_native(native, plaintext, instance)
            replaced = current_native[0].id if current_native else None
            grace_until = None
        else:
            raise ValidationFailedError("A token is native or gateway.")
        action = "tokens.rotate" if replaced else "tokens.create"
        await self._audit_token(principal, action, account, issued.kind, issued.prefix, issued.instance)
        await self._accounts.commit()
        return TokenIssued(
            view=(await self._views([account]))[0], token=issued, replaced_id=replaced, grace_until=grace_until
        )

    async def _token_instance(self, account: ServiceAccount, ref: str | None) -> Instance:
        if ref is None:
            if len(account.instance_ids) != 1:
                raise ValidationFailedError("Say which instance the native token is for.")
            ref = account.instance_ids[0]
        instance = await self._instances.get(ref)
        if instance is None or instance.id not in account.instance_ids:
            raise ValidationFailedError(f"{account.principal} doesn't apply on {ref}.")
        return instance

    async def revoke_token(self, principal: Principal, ref: str, token_ref: str) -> AccountView:
        """Revoke one token now, by id or by its display prefix."""
        _ = await self._authorizer.require(principal, MANAGE)
        account = await self._account(ref)
        view = (await self._views([account]))[0]
        now = utcnow()
        native = next((t for t in view.native_tokens if token_ref in {t.id, t.token_prefix}), None)
        gateway = next((t for t in view.gateway_tokens if token_ref in {t.id, t.prefix}), None)
        if native is not None:
            if native.active:
                _ = await self._revoke_upstream(native)
                await self._accounts.save_native(native.revoke(now))
            instance = next((i for i in view.instances if i.id == native.instance_id), None)
            await self._audit_token(principal, "tokens.revoke", account, "native", native.token_prefix, instance)
        elif gateway is not None:
            await self._accounts.save_gateway(gateway.revoke(now, "revoked"))
            await self._audit_token(principal, "tokens.revoke", account, "gateway", gateway.prefix, None)
        else:
            raise NotFoundError(f"{account.principal} has no token {token_ref!r}.")
        await self._accounts.commit()
        return (await self._views([account]))[0]

    async def _audit_token(
        self,
        principal: Principal,
        action: str,
        account: ServiceAccount,
        kind: TokenKind,
        prefix: str,
        instance: Instance | None,
    ) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="service_account_token",
                resource_id=account.id,
                resource_display=f"{prefix}… ({account.principal})",
                instance_id=instance.id if instance else None,
                fields={
                    "account": account.principal,
                    "kind": kind,
                    "token": f"{prefix}…",
                    "where": f" on {instance.display_name}" if instance else "",
                },
            )
        )

    # ------------------------------------------------------------------ delete

    async def delete(self, principal: Principal, ref: str) -> None:
        """Revoke every token (natively on each instance), remove the bindings, keep the row as deleted."""
        _ = await self._authorizer.require(principal, MANAGE)
        account = await self._account(ref)
        now = utcnow()
        failed: list[str] = []
        for native in await self._accounts.native_tokens([account.id]):
            if not native.active:
                continue
            if await self._revoke_upstream(native, quiet=True):
                await self._accounts.save_native(native.revoke(now))
            else:
                failed.append(native.instance_id)
        if failed:
            await self._accounts.commit()
            names = [(await self._instances.get(i) or i) for i in failed]
            labels = ", ".join(n.display_name if isinstance(n, Instance) else n for n in names)
            raise NativeProvisioningError(
                f"Couldn't revoke the native token on {labels}; {account.principal} was kept. Try again.",
                extra={"instance_ids": failed},
            )
        for gateway in await self._accounts.gateway_tokens([account.id]):
            await self._accounts.save_gateway(gateway.revoke(now, "account deleted"))
        _ = await self._access.unbind_principal("service_account", account.id)
        await self._accounts.save(account.delete(now))
        _ = await self._audit.record(
            AuditEntry(
                action="service_accounts.delete",
                actor=actor_of(principal),
                resource_kind="service_account",
                resource_id=account.id,
                resource_display=account.principal,
                fields={"account": account.principal},
            )
        )
        await self._accounts.commit()
        # Again after the commit: nothing cached in between keeps the removed grants.
        await bump_access_generation(self._store)

    # ------------------------------------------------------------------ poll & expiry

    async def poll(self) -> PollReport:
        """Read ``last_used_at`` (and revocations) from each instance; expire accounts and settle rotations."""
        now = utcnow()
        report = PollReport()
        by_instance: dict[str, list[NativeToken]] = {}
        for token in await self._accounts.active_native_tokens():
            by_instance.setdefault(token.instance_id, []).append(token)
        for instance_id, tokens in by_instance.items():
            await self._poll_instance(instance_id, tokens, now, report)
        for account in await self._accounts.list():
            if account.expired(now):
                report.expired += await self._expire(account, now)
            for gateway in await self._accounts.gateway_tokens([account.id]):
                settled = gateway.settle(now)
                if settled != gateway:
                    await self._accounts.save_gateway(settled)
                    report.settled += 1
        await self._accounts.commit()
        return report

    async def _poll_instance(
        self, instance_id: str, tokens: Sequence[NativeToken], now: datetime, report: PollReport
    ) -> None:
        instance = await self._instances.get(instance_id)
        if instance is None:
            return
        try:
            remote = await self._remote_accounts(instance)
        except AgentOSError as exc:
            log.warning("service_accounts.poll_failed", instance=instance_id, error=str(exc))
            report.failed_instances.append(instance_id)
            return
        for token in tokens:
            item = remote.get(token.agentos_sa_id)
            if item is None:
                continue
            updated = token.observed(
                last_used_at=_time(item.get("last_used_at")),
                revoked_at=_time(item.get("revoked_at")),
                expires_at=_time(item.get("expires_at")),
                now=now,
            )
            if updated != token:
                await self._accounts.save_native(updated)
                report.updated += 1

    async def _remote_accounts(self, instance: Instance) -> dict[str, Mapping[str, Any]]:
        found: dict[str, Mapping[str, Any]] = {}
        for page in range(1, POLL_MAX_PAGES + 1):
            raw = await self._instances.system_call(
                instance,
                "GET",
                "/service-accounts",
                params={"include_revoked": "true", "page": page, "limit": POLL_PAGE_SIZE},
            )
            body = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
            items = cast("list[Any]", body.get("data") or [])
            for item in items:
                if isinstance(item, dict):
                    entry = cast("dict[str, Any]", item)
                    found[str(entry.get("id"))] = entry
            meta = cast("dict[str, Any]", body.get("meta") or {})
            total = int(meta.get("total_count") or 0)
            if not items or page * POLL_PAGE_SIZE >= total:
                break
        return found

    async def _expire(self, account: ServiceAccount, now: datetime) -> int:
        changed = 0
        for native in await self._accounts.native_tokens([account.id]):
            if native.active:
                _ = await self._revoke_upstream(native, quiet=True)
                await self._accounts.save_native(
                    native.observed(last_used_at=None, revoked_at=None, expires_at=account.expires_at, now=now)
                )
                changed += 1
        for gateway in await self._accounts.gateway_tokens([account.id]):
            if gateway.status == "active":
                await self._accounts.save_gateway(gateway.expire(account.expires_at or now))
                changed += 1
        if changed:
            _ = await self._audit.record(
                AuditEntry(
                    action="service_accounts.expire",
                    actor=actor_of(SYSTEM_PRINCIPAL),
                    resource_kind="service_account",
                    resource_id=account.id,
                    resource_display=account.principal,
                    fields={"account": account.principal},
                    via="job",
                )
            )
        return changed


@dataclass(slots=True)
class PollReport:
    updated: int = 0
    expired: int = 0
    settled: int = 0
    failed_instances: list[str] = field(default_factory=list[str])
