"""Dependency wiring of the settings module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_settings.application.use_cases import GetOrgSettings, OrgSettingsRepository, UpdateOrgSettings
from agnostic_settings.facade import OrgSettingsFacade, OrgSettingsFacadeImpl, OrgSettingsReader, OrgSettingsReaderImpl
from agnostic_settings.infrastructure.repository import SqlOrgSettingsRepository


class SettingsProvider(Provider):
    scope = Scope.REQUEST

    repository = provide(SqlOrgSettingsRepository, provides=OrgSettingsRepository)
    get = provide(GetOrgSettings)
    update = provide(UpdateOrgSettings)
    facade = provide(OrgSettingsFacadeImpl, provides=OrgSettingsFacade)
    reader = provide(OrgSettingsReaderImpl, provides=OrgSettingsReader)
