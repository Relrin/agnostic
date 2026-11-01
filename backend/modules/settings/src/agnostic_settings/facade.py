"""The only import surface other modules may use: read and change org settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agnostic_kernel.auth import Principal
from agnostic_settings.application.use_cases import GetOrgSettings, UpdateOrgSettings
from agnostic_settings.domain.org_settings import OrgSettings

__all__ = ["OrgSettings", "OrgSettingsFacade", "OrgSettingsFacadeImpl", "OrgSettingsReader", "OrgSettingsReaderImpl"]


class OrgSettingsReader(Protocol):
    """Read-only view (what the access module needs; it can't depend on the writer, which needs authorization)."""

    async def get(self) -> OrgSettings: ...


class OrgSettingsReaderImpl:
    def __init__(self, get: GetOrgSettings) -> None:
        self._get = get

    async def get(self) -> OrgSettings:
        return await self._get()


class OrgSettingsFacade(Protocol):
    async def get(self) -> OrgSettings: ...
    async def update(self, principal: Principal, changes: Mapping[str, Any], *, commit: bool = True) -> OrgSettings:
        """Requires ``settings:write``; audited; the caller may commit as part of a larger change."""
        ...


class OrgSettingsFacadeImpl:
    def __init__(self, get: GetOrgSettings, update: UpdateOrgSettings) -> None:
        self._get = get
        self._update = update

    async def get(self) -> OrgSettings:
        return await self._get()

    async def update(self, principal: Principal, changes: Mapping[str, Any], *, commit: bool = True) -> OrgSettings:
        return await self._update(principal, changes, commit=commit)
