"""Org settings > Authentication: sign-in providers managed in the app, and the org auth policy.

Everything here needs ``settings:write`` (Owners and Administrators); changes also need a recent sign-in or
step-up, and are audited. Secrets are sealed at rest and never returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.application.policy import AuthPolicies
from agnostic_identity.application.ports import (
    AuthPolicyRepository,
    CertificateInfo,
    CredentialRepository,
    ExternalIdentityRepository,
    LoginProviderRepository,
    MembershipDirectory,
    SamlServiceProvider,
    SignInClients,
    SpEndpoints,
    StoredProvider,
    UserRepository,
)
from agnostic_identity.application.sessions import RecentAuth
from agnostic_identity.application.signin import SignInPolicy
from agnostic_identity.domain.policy import AuthPolicy, InvalidPolicyError, MfaPolicy
from agnostic_identity.domain.providers import (
    NAME_ID_UNSPECIFIED,
    PRESETS,
    AttributeMapping,
    ManagedBy,
    Preset,
    ProviderConfig,
    ProviderConfigError,
    ProviderKind,
    SamlIdp,
    SignInProtocol,
    check_provider_id,
    resolve_provider,
)
from agnostic_identity.domain.users import SessionPolicy, User
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError

ADMIN_SCOPE = "settings:write"


@dataclass(frozen=True, slots=True)
class ProviderView:
    config: ProviderConfig
    enabled: bool
    has_client_secret: bool
    callback_url: str | None
    """OIDC / OAuth 2: the redirect URI to register at the provider."""
    service_provider: SpEndpoints | None
    """SAML: this installation's entity id and ACS URL to register at the IdP."""
    certificates: list[CertificateInfo] = field(default_factory=list[CertificateInfo])
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def managed_by(self) -> ManagedBy:
        return self.config.managed_by


def _values(config: ProviderConfig, enabled: bool) -> dict[str, Any]:
    """A provider as the flat values the admin API speaks (secrets included: only for merging changes)."""
    values: dict[str, Any] = {
        "kind": config.kind.value,
        "preset": config.preset.value,
        "display_name": config.display_name,
        "enabled": enabled,
        "allowed_email_domains": list(config.allowed_email_domains),
        "jit_provisioning": config.jit_provisioning,
    }
    if config.saml is None:
        values.update(
            issuer=config.issuer,
            base_url=config.base_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scopes=list(config.scopes),
            trust_unverified_email=config.trust_unverified_email,
        )
    else:
        idp = config.saml
        values.update(
            metadata_url=idp.metadata_url,
            idp_entity_id=idp.entity_id,
            sso_url=idp.sso_url,
            certificates=list(idp.certificates),
            name_id_format=idp.name_id_format,
            attribute_mapping={
                "email": idp.attributes.email,
                "name": idp.attributes.name,
                "groups": idp.attributes.groups,
            },
        )
    return values


_PRESET_DERIVED = ("issuer", "base_url", "scopes")


def _carried_over(before: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """The stored values an update keeps unless it sets them.

    Values a preset fills in (issuer, instance URL, scopes) don't carry over to another preset:
    a GitHub provider switched to GitLab must not keep ``https://github.com`` as its GitLab URL.
    For GitLab the instance URL and the issuer are one setting and the URL wins, so changing the URL drops the
    stored issuer.
    """
    kept = dict(before)
    if "preset" in changes and changes["preset"] != before.get("preset"):
        for key in _PRESET_DERIVED:
            _ = kept.pop(key, None)
    elif (changes.get("preset") or before.get("preset")) == Preset.GITLAB.value and "base_url" in changes:
        _ = kept.pop("issuer", None)
    return kept


def _public(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key != "client_secret"}


def _diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) == after.get(key):
            continue
        if key == "client_secret":
            diff[key] = {"changed": True}
        elif key == "certificates":
            diff[key] = {"before": len(before.get(key) or []), "after": len(after.get(key) or [])}
        else:
            diff[key] = {"before": before.get(key), "after": after.get(key)}
    return diff


class _AdminBase:
    def __init__(
        self,
        authorizer: Authorizer,
        recent: RecentAuth,
        audit: AuditLog,
        users: UserRepository,
        clients: SignInClients,
        policy: SignInPolicy,
        saml: SamlServiceProvider,
    ) -> None:
        self._authorizer = authorizer
        self._recent = recent
        self._audit = audit
        self._users = users
        self._clients = clients
        self._policy = policy
        self._saml = saml

    async def _may_change(self, principal: Principal) -> None:
        _ = await self._authorizer.require(principal, ADMIN_SCOPE)
        await self._recent.require(principal)

    def _view(self, config: ProviderConfig, *, enabled: bool, stored: StoredProvider | None = None) -> ProviderView:
        certificates: list[CertificateInfo] = []
        if config.saml is not None:
            for pem in config.saml.certificates:
                try:
                    certificates.append(self._saml.describe_certificate(pem))
                except ProviderConfigError:
                    continue
        return ProviderView(
            config=config,
            enabled=enabled,
            has_client_secret=bool(config.client_secret),
            callback_url=self._policy.callback_url(config.id) if config.saml is None else None,
            service_provider=self._policy.service_provider(config.id) if config.saml is not None else None,
            certificates=certificates,
            created_by=stored.created_by if stored else None,
            created_at=stored.created_at if stored else None,
            updated_at=stored.updated_at if stored else None,
        )


class _ProviderAdmin(_AdminBase):
    def __init__(
        self,
        authorizer: Authorizer,
        recent: RecentAuth,
        audit: AuditLog,
        users: UserRepository,
        clients: SignInClients,
        policy: SignInPolicy,
        saml: SamlServiceProvider,
        providers: LoginProviderRepository,
        externals: ExternalIdentityRepository,
        policies: AuthPolicies,
    ) -> None:
        super().__init__(authorizer, recent, audit, users, clients, policy, saml)
        self._providers = providers
        self._externals = externals
        self._policies = policies

    async def _stored(self, provider_id: str) -> StoredProvider:
        stored = await self._providers.get(provider_id)
        if stored is None:
            if any(config.id == provider_id for config in self._clients.configured()):
                raise ConflictError(
                    f"{provider_id!r} is configured in the server settings (AGNOSTIC_IDENTITY__PROVIDERS__*); "
                    "change it there."
                )
            raise NotFoundError(f"There is no sign-in provider {provider_id!r}.")
        return stored

    async def _build(
        self, provider_id: str, values: dict[str, Any], *, metadata_xml: str | None, refresh_metadata: bool
    ) -> ProviderConfig:
        try:
            preset = Preset(values.get("preset") or Preset.OIDC.value)
            kind = ProviderKind(values.get("kind") or ProviderKind.OIDC.value)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
        protocol = PRESETS[preset].protocol
        if (kind is ProviderKind.SAML) != (protocol is SignInProtocol.SAML):
            raise ValidationFailedError(f"The {preset.value!r} preset isn't a {kind.value} provider.")
        try:
            saml = (
                await self._saml_idp(values, metadata_xml=metadata_xml, refresh=refresh_metadata)
                if protocol is SignInProtocol.SAML
                else None
            )
            return resolve_provider(
                check_provider_id(provider_id),
                preset=preset,
                client_id=str(values.get("client_id") or ""),
                client_secret=values.get("client_secret") or None,
                display_name=values.get("display_name") or None,
                issuer=values.get("issuer") or None,
                base_url=values.get("base_url") or None,
                scopes=values.get("scopes") or None,
                allowed_email_domains=values.get("allowed_email_domains") or (),
                jit_provisioning=bool(values.get("jit_provisioning")),
                trust_unverified_email=bool(values.get("trust_unverified_email")),
                saml=saml,
                managed_by=ManagedBy.DATABASE,
            )
        except ProviderConfigError as exc:
            raise ValidationFailedError(str(exc)) from exc

    async def _saml_idp(self, values: dict[str, Any], *, metadata_xml: str | None, refresh: bool) -> SamlIdp:
        metadata_url = values.get("metadata_url") or None
        if metadata_url is not None and not str(metadata_url).startswith(("https://", "http://")):
            raise ProviderConfigError("The metadata URL must be an http(s) URL.")
        parsed = None
        if metadata_xml:
            parsed = self._saml.parse_idp_metadata(metadata_xml)
        elif metadata_url and refresh:
            parsed = self._saml.parse_idp_metadata(await self._saml.fetch_idp_metadata(str(metadata_url)))
        if parsed is not None:
            explicit = values.get("_explicit", set[str]())
            if "idp_entity_id" not in explicit:
                values["idp_entity_id"] = parsed.entity_id
            if "sso_url" not in explicit:
                values["sso_url"] = parsed.sso_url
            if "certificates" not in explicit:
                values["certificates"] = list(parsed.certificates)
        listed = cast("list[str]", values.get("certificates") or [])
        certificates = tuple(self._saml.normalize_certificate(str(text)) for text in listed)
        mapping: Mapping[str, Any] = values.get("attribute_mapping") or {}
        return SamlIdp(
            entity_id=str(values.get("idp_entity_id") or ""),
            sso_url=str(values.get("sso_url") or ""),
            certificates=tuple(dict.fromkeys(certificates)),
            metadata_url=metadata_url,
            name_id_format=str(values.get("name_id_format") or NAME_ID_UNSPECIFIED),
            attributes=AttributeMapping(
                email=mapping.get("email") or None,
                name=mapping.get("name") or None,
                groups=mapping.get("groups") or None,
            ),
        )

    async def _keeps_sso_available(self, without: str) -> None:
        """With SSO enforced, the last enabled provider can't go away (only the break-glass Owner could sign in)."""
        if not (await self._policies.current()).enforce_sso:
            return
        if not any(config.id != without for config in await self._clients.all()):
            raise ConflictError("SSO is enforced: keep at least one enabled provider, or stop enforcing SSO first.")


class ListLoginProviders(_ProviderAdmin):
    async def __call__(self, principal: Principal) -> list[ProviderView]:
        _ = await self._authorizer.require(principal, ADMIN_SCOPE)
        views = [self._view(config, enabled=True) for config in self._clients.configured()]
        views += [
            self._view(stored.config, enabled=stored.enabled, stored=stored) for stored in await self._providers.list()
        ]
        return sorted(views, key=lambda view: view.config.id)


class GetLoginProvider(_ProviderAdmin):
    async def __call__(self, principal: Principal, provider_id: str) -> ProviderView:
        _ = await self._authorizer.require(principal, ADMIN_SCOPE)
        for config in self._clients.configured():
            if config.id == provider_id:
                return self._view(config, enabled=True)
        stored = await self._stored(provider_id)
        return self._view(stored.config, enabled=stored.enabled, stored=stored)


class CreateLoginProvider(_ProviderAdmin):
    async def __call__(
        self, principal: Principal, provider_id: str, values: Mapping[str, Any], *, metadata_xml: str | None = None
    ) -> ProviderView:
        await self._may_change(principal)
        taken = {config.id for config in self._clients.configured()}
        if provider_id in taken or await self._providers.get(provider_id) is not None:
            raise ConflictError(f"A sign-in provider {provider_id!r} already exists.")
        merged = {**values, "_explicit": set(values)}
        config = await self._build(provider_id, merged, metadata_xml=metadata_xml, refresh_metadata=True)
        enabled = bool(values.get("enabled", True))
        stored = await self._providers.add(config, enabled=enabled, created_by=principal.id)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.providers.create",
                actor=actor_of(principal),
                resource_kind="login_provider",
                resource_id=provider_id,
                resource_display=config.display_name,
                fields={"provider": config.display_name, "kind": config.kind.value},
                diff={key: {"after": value} for key, value in _public(_values(config, enabled)).items()},
            )
        )
        await self._users.commit()
        return self._view(stored.config, enabled=stored.enabled, stored=stored)


class UpdateLoginProvider(_ProviderAdmin):
    async def __call__(
        self,
        principal: Principal,
        provider_id: str,
        changes: Mapping[str, Any],
        *,
        metadata_xml: str | None = None,
        refresh_metadata: bool = False,
    ) -> ProviderView:
        await self._may_change(principal)
        stored = await self._stored(provider_id)
        before = _values(stored.config, stored.enabled)
        if "kind" in changes and changes["kind"] != before["kind"]:
            raise ValidationFailedError("A provider's kind can't change; create a new provider instead.")
        merged = {**_carried_over(before, changes), **changes, "_explicit": set(changes)}
        refetch = refresh_metadata or (
            "metadata_url" in changes and changes["metadata_url"] != before.get("metadata_url")
        )
        config = await self._build(provider_id, merged, metadata_xml=metadata_xml, refresh_metadata=refetch)
        enabled = bool(merged.get("enabled", True))
        if not enabled and stored.enabled:
            await self._keeps_sso_available(without=provider_id)
        after = _values(config, enabled)
        diff = _diff(before, after)
        if not diff:
            return self._view(stored.config, enabled=stored.enabled, stored=stored)
        saved = await self._providers.save(config, enabled=enabled)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.providers.update",
                actor=actor_of(principal),
                resource_kind="login_provider",
                resource_id=provider_id,
                resource_display=config.display_name,
                fields={"provider": config.display_name, "changes": ", ".join(diff)},
                diff=diff,
            )
        )
        await self._users.commit()
        return self._view(saved.config, enabled=saved.enabled, stored=saved)


class DeleteLoginProvider(_ProviderAdmin):
    async def __call__(self, principal: Principal, provider_id: str) -> None:
        await self._may_change(principal)
        stored = await self._stored(provider_id)
        if stored.enabled:
            await self._keeps_sso_available(without=provider_id)
        unlinked = await self._externals.unlink_provider(provider_id)
        await self._providers.delete(provider_id)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.providers.delete",
                actor=actor_of(principal),
                resource_kind="login_provider",
                resource_id=provider_id,
                resource_display=stored.config.display_name,
                fields={"provider": stored.config.display_name, "unlinked": str(unlinked)},
            )
        )
        await self._users.commit()


class ProviderSpMetadata(_ProviderAdmin):
    """The SAML SP metadata of this installation for one provider (the IdP imports it)."""

    async def __call__(self, principal: Principal | None, provider_id: str) -> str:
        if principal is not None:
            _ = await self._authorizer.require(principal, ADMIN_SCOPE)
        config = await self._clients.config(provider_id)
        if config is None and principal is not None:
            stored = await self._providers.get(provider_id)  # disabled providers too, for admins
            config = stored.config if stored else None
        if config is None or config.saml is None:
            raise NotFoundError(f"There is no SAML provider {provider_id!r}.")
        return self._saml.sp_metadata(
            self._policy.service_provider(provider_id), name_id_format=config.saml.name_id_format
        )


@dataclass(frozen=True, slots=True)
class PolicyView:
    policy: AuthPolicy
    break_glass_user: User | None
    defaults: SessionPolicy


class _PolicyAdmin(_AdminBase):
    def __init__(
        self,
        authorizer: Authorizer,
        recent: RecentAuth,
        audit: AuditLog,
        users: UserRepository,
        clients: SignInClients,
        policy: SignInPolicy,
        saml: SamlServiceProvider,
        policies: AuthPolicies,
        repository: AuthPolicyRepository,
        credentials: CredentialRepository,
        directory: MembershipDirectory,
    ) -> None:
        super().__init__(authorizer, recent, audit, users, clients, policy, saml)
        self._policies = policies
        self._repository = repository
        self._credentials = credentials
        self._directory = directory

    async def _policy_view(self, policy: AuthPolicy) -> PolicyView:
        user = await self._users.get(policy.break_glass_user_id) if policy.break_glass_user_id else None
        return PolicyView(policy=policy, break_glass_user=user, defaults=self._policies.defaults)


class GetAuthPolicy(_PolicyAdmin):
    async def __call__(self, principal: Principal) -> PolicyView:
        _ = await self._authorizer.require(principal, ADMIN_SCOPE)
        return await self._policy_view(await self._repository.load())


class UpdateAuthPolicy(_PolicyAdmin):
    async def __call__(
        self,
        principal: Principal,
        *,
        enforce_sso: bool,
        break_glass_user_id: str | None,
        session_idle_minutes: int | None,
        session_absolute_hours: int | None,
        mfa_policy: MfaPolicy,
    ) -> PolicyView:
        await self._may_change(principal)
        current = await self._repository.load()
        try:
            updated = current.updated(
                enforce_sso=enforce_sso,
                break_glass_user_id=break_glass_user_id or None,
                session_idle_minutes=session_idle_minutes,
                session_absolute_hours=session_absolute_hours,
                mfa_policy=mfa_policy,
            )
        except InvalidPolicyError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if updated.break_glass_user_id:
            await self._check_break_glass(updated.break_glass_user_id)
        if updated.enforce_sso and not await self._clients.all():
            raise ValidationFailedError("Add and enable an SSO provider before enforcing SSO.")
        before, after = _policy_values(current), _policy_values(updated)
        diff = {key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]}
        if not diff:
            return await self._policy_view(current)
        stored = await self._repository.store(updated, updated_by=principal.id)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.policy.update",
                actor=actor_of(principal),
                resource_kind="auth_policy",
                resource_display="authentication policy",
                fields={"changes": ", ".join(diff)},
                diff=diff,
            )
        )
        await self._users.commit()
        await self._policies.forget()
        return await self._policy_view(stored)

    async def _check_break_glass(self, user_id: str) -> None:
        user = await self._users.get(user_id)
        membership = await self._directory.membership(user_id) if user else None
        if user is None or not user.active or membership is None or not membership.active:
            raise ValidationFailedError("The break-glass account must be an active member.")
        if membership.org_role != "owner":
            raise ValidationFailedError("The break-glass account must be an Owner.")
        if await self._credentials.password_hash(user_id) is None:
            raise ValidationFailedError("The break-glass account needs a password (it signs in without SSO).")


def _policy_values(policy: AuthPolicy) -> dict[str, Any]:
    return {
        "enforce_sso": policy.enforce_sso,
        "break_glass_user_id": policy.break_glass_user_id,
        "session_idle_minutes": policy.session_idle_minutes,
        "session_absolute_hours": policy.session_absolute_hours,
        "mfa_policy": policy.mfa_policy.value,
    }
