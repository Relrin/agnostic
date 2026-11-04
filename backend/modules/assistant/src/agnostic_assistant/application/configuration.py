"""The org's AI features: reading and changing the provider, budgets and redaction, and what people see."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from agnostic_assistant.application.limits import USE_SCOPE
from agnostic_assistant.application.ports import AnswerEngine, AssistantStore, Connection, EngineError
from agnostic_assistant.domain.budget import month_of
from agnostic_assistant.domain.settings import FEATURES, AiSettings, Feature, SettingsError
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import IdentityFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ValidationFailedError, VersionConflictError

READ_SCOPE = "settings:read"
WRITE_SCOPE = "settings:write"


@dataclass(frozen=True, slots=True)
class Status:
    """What a person's web app needs to know to show (or hide) AI features."""

    installed: bool
    features: Mapping[Feature, bool]
    can_use: bool
    provider: str | None
    data_notice: str | None
    month: str
    org_tokens: int
    org_limit: int | None
    user_tokens: int
    user_limit: int | None
    requests_per_minute: int


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    ok: bool
    model: str
    latency_ms: int | None
    detail: str


class AiFeatures:
    def __init__(
        self,
        store: AssistantStore,
        authorizer: Authorizer,
        identity: IdentityFacade,
        engine: AnswerEngine,
        audit: AuditLog,
    ) -> None:
        self._store = store
        self._authorizer = authorizer
        self._identity = identity
        self._engine = engine
        self._audit = audit

    async def get(self, principal: Principal) -> AiSettings:
        _ = await self._authorizer.require(principal, READ_SCOPE)
        return await self._store.settings()

    async def update(
        self, principal: Principal, changes: Mapping[str, Any], *, api_key: str | None, version: int | None
    ) -> AiSettings:
        """``api_key``: ``None`` keeps the stored key, ``""`` removes it, anything else replaces it."""
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        key_changed = api_key is not None
        if key_changed:
            await self._identity.require_recent_auth(principal)
        before = await self._store.settings()
        if version is not None and version != before.version:
            raise VersionConflictError("Someone else changed the AI settings; reload and try again.")
        try:
            after = before.updated(changes)
        except SettingsError as exc:
            raise ValidationFailedError(str(exc), extra={"fields": [exc.field]}) from exc
        if key_changed:
            after = replace(after, has_api_key=bool(api_key))
        lines = after.diff(before, key_changed=key_changed)
        if not lines:
            return before
        saved = await self._store.save_settings(after, api_key=api_key, key_changed=key_changed, by=principal.id)
        _ = await self._audit.record(
            AuditEntry(
                action="assistant.settings.update",
                actor=actor_of(principal),
                resource_kind="assistant_settings",
                resource_display="AI features",
                decision="allowed",
                scope_checked=WRITE_SCOPE,
                fields={"state": "on" if saved.enabled else "off", "model": saved.models.get("assistant") or "none"},
                diff={"title": "AI features", "lines": lines, "note": None},
            )
        )
        await self._store.commit()
        return saved

    async def check(self, principal: Principal, feature: Feature = "assistant") -> ConnectionCheck:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        settings = await self._store.settings()
        model = settings.model_for(feature)
        if model is None:
            raise ValidationFailedError("Choose a model first.", extra={"fields": ["models"]})
        connection = Connection(
            settings.endpoint, await self._store.api_key(), settings.api_version, settings.temperature
        )
        started = time.monotonic()
        try:
            reply = await self._engine.check(model, connection)
        except EngineError as exc:
            return ConnectionCheck(ok=False, model=model, latency_ms=None, detail=str(exc))
        latency = round((time.monotonic() - started) * 1000)
        return ConnectionCheck(
            ok=True, model=model, latency_ms=latency, detail=f"The model answered in {latency} ms: {reply[:80]!r}"
        )

    async def status(self, principal: Principal) -> Status:
        settings = await self._store.settings()
        month = month_of(utcnow())
        org, user = await self._store.spent(month, principal.id)
        can_use = (await self._authorizer.check(principal, USE_SCOPE)).allowed
        return Status(
            installed=True,
            features={feature: settings.available(feature) for feature in FEATURES},
            can_use=can_use,
            provider=settings.provider if settings.enabled else None,
            data_notice=settings.data_notice,
            month=month,
            org_tokens=org,
            org_limit=settings.monthly_token_budget,
            user_tokens=user,
            user_limit=settings.user_monthly_tokens,
            requests_per_minute=settings.requests_per_minute,
        )
