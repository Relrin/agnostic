"""Dependency wiring of the directory module."""

from __future__ import annotations

from collections.abc import AsyncIterator

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_directory.application.admin import DirectorySettingsAdmin, MappingRules, ScimAdmin
from agnostic_directory.application.claims import ClaimGroups
from agnostic_directory.application.google import GoogleSettings, GoogleSyncRunner
from agnostic_directory.application.groups import Groups, GroupsContext
from agnostic_directory.application.org_groups import OrgGroups
from agnostic_directory.application.ports import (
    DirectoryConfigRepository,
    GoogleDirectory,
    GroupRepository,
    MappingRuleRepository,
    ScimRepository,
)
from agnostic_directory.application.reconcile import Reconcile
from agnostic_directory.application.scim import ScimAuth, ScimGroups, ScimRecorder, ScimUsers
from agnostic_directory.application.sync import Deprovisioner, DirectoryPolicy, RuleApplier, SyncContext
from agnostic_directory.facade import DirectoryFacade, DirectoryFacadeImpl
from agnostic_directory.infrastructure.google import HttpGoogleDirectory
from agnostic_directory.infrastructure.repository import SqlGroupRepository
from agnostic_directory.infrastructure.sync_repository import (
    SqlDirectoryConfigRepository,
    SqlMappingRuleRepository,
    SqlScimRepository,
)
from agnostic_identity.facade import ExternalGroupsSync
from agnostic_kernel.settings import Settings
from agnostic_org.facade import GroupDirectory

SCIM_PATH = "/scim/v2"


class DirectoryProvider(Provider):
    scope = Scope.REQUEST

    groups_repository = provide(SqlGroupRepository, provides=GroupRepository)
    scim_repository = provide(SqlScimRepository, provides=ScimRepository)
    rules_repository = provide(SqlMappingRuleRepository, provides=MappingRuleRepository)
    config_repository = provide(SqlDirectoryConfigRepository, provides=DirectoryConfigRepository)
    facade = provide(DirectoryFacadeImpl, provides=DirectoryFacade)
    context = provide(GroupsContext)
    groups = provide(Groups)
    claims = provide(ClaimGroups, provides=ExternalGroupsSync)
    org_groups = provide(OrgGroups, provides=GroupDirectory)

    sync_context = provide(SyncContext)
    deprovisioner = provide(Deprovisioner)
    rule_applier = provide(RuleApplier)
    scim_auth = provide(ScimAuth)
    scim_recorder = provide(ScimRecorder)
    scim_users = provide(ScimUsers)
    scim_groups = provide(ScimGroups)
    scim_admin = provide(ScimAdmin)
    mapping_rules = provide(MappingRules)
    directory_settings = provide(DirectorySettingsAdmin)
    google_settings = provide(GoogleSettings)
    google_runner = provide(GoogleSyncRunner)
    reconcile = provide(Reconcile)

    @provide(scope=Scope.APP)
    def policy(self, kernel: Settings) -> DirectoryPolicy:
        return DirectoryPolicy(scim_base_url=f"{kernel.public_url()}{SCIM_PATH}")

    @provide(scope=Scope.APP)
    async def google(self) -> AsyncIterator[GoogleDirectory]:
        directory = HttpGoogleDirectory()
        yield directory
        await directory.aclose()
