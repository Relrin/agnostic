"""Reading and changing org settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ValidationFailedError
from agnostic_settings.domain.org_settings import ACCESS_RELEVANT, InvalidSettingError, OrgSettings

WRITE_SCOPE = "settings:write"


class OrgSettingsRepository(Protocol):
    async def load(self) -> dict[str, Any]: ...
    async def store(self, values: Mapping[str, Any], updated_by: str) -> None: ...
    async def commit(self) -> None: ...


class GetOrgSettings:
    def __init__(self, repository: OrgSettingsRepository) -> None:
        self._repository = repository

    async def __call__(self) -> OrgSettings:
        return OrgSettings.from_values(await self._repository.load())


class UpdateOrgSettings:
    def __init__(
        self,
        repository: OrgSettingsRepository,
        authorizer: Authorizer,
        audit: AuditLog,
        store: EphemeralStore,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer
        self._audit = audit
        self._store = store

    async def __call__(self, principal: Principal, changes: Mapping[str, Any], *, commit: bool = True) -> OrgSettings:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        current = OrgSettings.from_values(await self._repository.load())
        try:
            updated = current.updated(changes)
        except InvalidSettingError as exc:
            raise ValidationFailedError(str(exc)) from exc
        diff = current.diff(updated)
        if not diff:
            return current
        await self._repository.store({key: change["after"] for key, change in diff.items()}, principal.id)
        _ = await self._audit.record(
            AuditEntry(
                action="settings.org.update",
                actor=actor_of(principal),
                resource_kind="org_settings",
                resource_display="org settings",
                fields={"keys": ", ".join(sorted(diff))},
                diff=diff,
            )
        )
        if commit:
            await self._repository.commit()
        if ACCESS_RELEVANT & diff.keys():
            await bump_access_generation(self._store)
        return updated
