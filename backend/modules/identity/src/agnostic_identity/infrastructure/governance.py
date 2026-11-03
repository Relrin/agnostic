"""SQLAlchemy repositories for sign-in providers managed in the app, the org auth policy and second factors."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_identity.application.ports import StoredProvider
from agnostic_identity.domain.mfa import Factor, FactorKind, NewWebAuthnCredential, WebAuthnCredential
from agnostic_identity.domain.policy import AuthPolicy, MfaPolicy
from agnostic_identity.domain.providers import (
    AttributeMapping,
    ManagedBy,
    Preset,
    ProviderConfig,
    SamlIdp,
    resolve_provider,
)
from agnostic_identity.infrastructure.tables import AuthPolicyRow, CredentialRow, LoginProviderRow
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import new_id

RECOVERY = "recovery"
POLICY_ROW = 1
_FACTOR_KINDS = (FactorKind.TOTP.value, FactorKind.WEBAUTHN.value)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _rowcount(result: object) -> int:
    return cast("CursorResult[Any]", result).rowcount or 0


class SqlLoginProviderRepository:
    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    def _config_of(self, config: ProviderConfig) -> dict[str, Any]:
        if config.saml is not None:
            idp = config.saml
            return {
                "idp_entity_id": idp.entity_id,
                "sso_url": idp.sso_url,
                "certificates": list(idp.certificates),
                "metadata_url": idp.metadata_url,
                "name_id_format": idp.name_id_format,
                "attribute_mapping": {
                    "email": idp.attributes.email,
                    "name": idp.attributes.name,
                    "groups": idp.attributes.groups,
                },
            }
        return {
            "issuer": config.issuer,
            "base_url": config.base_url,
            "client_id": config.client_id,
            "client_secret": self._box.seal(config.client_secret.encode()) if config.client_secret else None,
            "scopes": list(config.scopes),
            "trust_unverified_email": config.trust_unverified_email,
        }

    def _to_domain(self, row: LoginProviderRow) -> StoredProvider:
        data = row.config
        updated_at = aware(row.updated_at)
        saml = None
        if row.kind == "saml":
            mapping = cast("dict[str, str | None]", data.get("attribute_mapping") or {})
            saml = SamlIdp(
                entity_id=str(data["idp_entity_id"]),
                sso_url=str(data["sso_url"]),
                certificates=tuple(cast("list[str]", data.get("certificates") or [])),
                metadata_url=data.get("metadata_url"),
                name_id_format=str(data["name_id_format"]),
                attributes=AttributeMapping(
                    email=mapping.get("email"), name=mapping.get("name"), groups=mapping.get("groups")
                ),
            )
        sealed = data.get("client_secret")
        config = resolve_provider(
            row.id,
            preset=Preset(row.preset),
            client_id=str(data.get("client_id") or ""),
            client_secret=self._box.open(str(sealed)).decode() if sealed else None,
            display_name=row.display_name,
            issuer=data.get("issuer"),
            base_url=data.get("base_url"),
            scopes=cast("list[str]", data.get("scopes") or []) or None,
            allowed_email_domains=row.allowed_email_domains,
            jit_provisioning=row.jit_provisioning,
            trust_unverified_email=bool(data.get("trust_unverified_email")),
            saml=saml,
            managed_by=ManagedBy.DATABASE,
            version=updated_at.isoformat(),
        )
        return StoredProvider(
            config=config,
            enabled=row.enabled,
            created_by=row.created_by,
            created_at=aware(row.created_at),
            updated_at=updated_at,
        )

    async def list(self) -> list[StoredProvider]:
        rows = await self._session.scalars(select(LoginProviderRow).order_by(LoginProviderRow.id))
        return [self._to_domain(row) for row in rows]

    async def get(self, provider_id: str) -> StoredProvider | None:
        row = await self._session.get(LoginProviderRow, provider_id)
        return self._to_domain(row) if row else None

    async def add(self, config: ProviderConfig, *, enabled: bool, created_by: str) -> StoredProvider:
        now = utcnow()
        row = LoginProviderRow(
            id=config.id,
            kind=config.kind.value,
            display_name=config.display_name,
            preset=config.preset.value,
            config=self._config_of(config),
            allowed_email_domains=list(config.allowed_email_domains),
            jit_provisioning=config.jit_provisioning,
            enabled=enabled,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    async def save(self, config: ProviderConfig, *, enabled: bool) -> StoredProvider:
        row = await self._session.get(LoginProviderRow, config.id)
        if row is None:
            raise NotFoundError(f"There is no sign-in provider {config.id!r}.")
        row.display_name = config.display_name
        row.preset = config.preset.value
        row.config = self._config_of(config)
        row.allowed_email_domains = list(config.allowed_email_domains)
        row.jit_provisioning = config.jit_provisioning
        row.enabled = enabled
        row.updated_at = utcnow()
        await self._session.flush()
        return self._to_domain(row)

    async def delete(self, provider_id: str) -> None:
        _ = await self._session.execute(delete(LoginProviderRow).where(LoginProviderRow.id == provider_id))


class SqlAuthPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self) -> AuthPolicy:
        row = await self._session.get(AuthPolicyRow, POLICY_ROW)
        if row is None:
            return AuthPolicy()
        return AuthPolicy(
            enforce_sso=row.enforce_sso,
            break_glass_user_id=row.break_glass_user_id,
            session_idle_minutes=row.session_idle_minutes,
            session_absolute_hours=row.session_absolute_hours,
            mfa_policy=MfaPolicy(row.mfa_policy),
            updated_by=row.updated_by,
            updated_at=aware(row.updated_at),
        )

    async def store(self, policy: AuthPolicy, *, updated_by: str) -> AuthPolicy:
        row = await self._session.get(AuthPolicyRow, POLICY_ROW)
        if row is None:
            row = AuthPolicyRow(id=POLICY_ROW)
            self._session.add(row)
        row.enforce_sso = policy.enforce_sso
        row.break_glass_user_id = policy.break_glass_user_id
        row.session_idle_minutes = policy.session_idle_minutes
        row.session_absolute_hours = policy.session_absolute_hours
        row.mfa_policy = policy.mfa_policy.value
        row.updated_by = updated_by
        row.updated_at = utcnow()
        await self._session.flush()
        return await self.load()


def _factor(row: CredentialRow) -> Factor:
    return Factor(
        id=row.id,
        kind=FactorKind(row.kind),
        label=row.label or "",
        created_at=aware(row.created_at),
        last_used_at=aware_or_none(row.last_used_at),
    )


class SqlMfaRepository:
    """Second factors in ``identity_credentials``: TOTP secrets are sealed, recovery codes are sha256 hashes."""

    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    async def factors(self, user_id: str) -> list[Factor]:
        rows = await self._session.scalars(
            select(CredentialRow)
            .where(CredentialRow.user_id == user_id, CredentialRow.kind.in_(_FACTOR_KINDS))
            .order_by(CredentialRow.created_at, CredentialRow.id)
        )
        return [_factor(row) for row in rows]

    async def totp_secret(self, user_id: str) -> tuple[str, str] | None:
        row = await self._session.scalar(
            select(CredentialRow).where(CredentialRow.user_id == user_id, CredentialRow.kind == FactorKind.TOTP.value)
        )
        return (row.id, self._box.open(row.secret_hash).decode()) if row else None

    async def set_totp(self, user_id: str, secret: str, *, label: str) -> Factor:
        _ = await self._session.execute(
            delete(CredentialRow).where(CredentialRow.user_id == user_id, CredentialRow.kind == FactorKind.TOTP.value)
        )
        row = CredentialRow(
            id=new_id("crd"),
            user_id=user_id,
            kind=FactorKind.TOTP.value,
            secret_hash=self._box.seal(secret.encode()),
            label=label,
            created_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        return _factor(row)

    async def webauthn_credentials(self, user_id: str) -> list[WebAuthnCredential]:
        rows = await self._session.scalars(
            select(CredentialRow).where(
                CredentialRow.user_id == user_id, CredentialRow.kind == FactorKind.WEBAUTHN.value
            )
        )
        credentials: list[WebAuthnCredential] = []
        for row in rows:
            data = row.data or {}
            credentials.append(
                WebAuthnCredential(
                    factor_id=row.id,
                    credential_id=_unb64(row.secret_hash),
                    public_key=_unb64(str(data["public_key"])),
                    sign_count=row.sign_count or 0,
                    transports=tuple(cast("list[str]", data.get("transports") or [])),
                )
            )
        return credentials

    async def add_webauthn(self, user_id: str, credential: NewWebAuthnCredential, *, label: str) -> Factor:
        row = CredentialRow(
            id=new_id("crd"),
            user_id=user_id,
            kind=FactorKind.WEBAUTHN.value,
            secret_hash=_b64(credential.credential_id),
            label=label,
            data={
                "public_key": _b64(credential.public_key),
                "transports": list(credential.transports),
                "aaguid": credential.aaguid,
            },
            sign_count=credential.sign_count,
            created_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        return _factor(row)

    async def update_sign_count(self, factor_id: str, sign_count: int, at: datetime) -> None:
        _ = await self._session.execute(
            update(CredentialRow).where(CredentialRow.id == factor_id).values(sign_count=sign_count, last_used_at=at)
        )

    async def mark_used(self, factor_id: str, at: datetime) -> None:
        _ = await self._session.execute(
            update(CredentialRow).where(CredentialRow.id == factor_id).values(last_used_at=at)
        )

    async def remove(self, user_id: str, factor_id: str) -> Factor | None:
        row = await self._session.scalar(
            select(CredentialRow).where(
                CredentialRow.id == factor_id,
                CredentialRow.user_id == user_id,
                CredentialRow.kind.in_(_FACTOR_KINDS),
            )
        )
        if row is None:
            return None
        factor = _factor(row)
        await self._session.delete(row)
        await self._session.flush()
        return factor

    async def remove_all(self, user_id: str) -> None:
        _ = await self._session.execute(
            delete(CredentialRow).where(
                CredentialRow.user_id == user_id, CredentialRow.kind.in_((*_FACTOR_KINDS, RECOVERY))
            )
        )

    async def replace_recovery_codes(self, user_id: str, code_hashes: Sequence[str]) -> None:
        _ = await self._session.execute(
            delete(CredentialRow).where(CredentialRow.user_id == user_id, CredentialRow.kind == RECOVERY)
        )
        now = utcnow()
        self._session.add_all(
            CredentialRow(id=new_id("crd"), user_id=user_id, kind=RECOVERY, secret_hash=code_hash, created_at=now)
            for code_hash in code_hashes
        )
        await self._session.flush()

    async def use_recovery_code(self, user_id: str, code_hash: str, at: datetime) -> bool:  # noqa: ARG002
        # Read first: a wrong code must not open a write transaction (the failure is audited on its own session).
        row_id = await self._session.scalar(
            select(CredentialRow.id).where(
                CredentialRow.user_id == user_id,
                CredentialRow.kind == RECOVERY,
                CredentialRow.secret_hash == code_hash,
            )
        )
        if row_id is None:
            return False
        result = await self._session.execute(
            delete(CredentialRow).where(CredentialRow.id == row_id, CredentialRow.kind == RECOVERY)
        )
        return _rowcount(result) > 0

    async def recovery_codes_left(self, user_id: str) -> int:
        count = await self._session.scalar(
            select(func.count()).where(CredentialRow.user_id == user_id, CredentialRow.kind == RECOVERY)
        )
        return int(count or 0)
