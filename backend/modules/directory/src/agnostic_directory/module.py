"""Module declaration: directory (groups, SCIM provisioning, Google Workspace sync, group claims at login)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_directory import jobs
from agnostic_directory.api.router import router
from agnostic_directory.api.scim import scim_router
from agnostic_directory.infrastructure.tables import DirectoryBase
from agnostic_directory.providers import SCIM_PATH, DirectoryProvider
from agnostic_directory.settings import DirectorySettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec


class DirectoryModule(BaseModule):
    name = "directory"
    version = "0.1.0"
    depends_on = ("identity", "org", "audit")

    def settings_model(self) -> type[BaseSettings] | None:
        return DirectorySettings

    def provide(self) -> Iterable[Provider]:
        return (DirectoryProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/directory", tags=("directory",)),
            RouterSpec(router=scim_router, prefix=SCIM_PATH, tags=("scim",), root=True),
        )

    def metadata(self) -> MetaData | None:
        return DirectoryBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        settings = DirectorySettings()
        specs: list[JobSpec] = []
        if settings.google_sync_cron:
            specs.append(JobSpec(name=jobs.GOOGLE_SYNC_TASK, func=jobs.google_sync, periodic=settings.google_sync_cron))
        if settings.reconcile_cron:
            specs.append(JobSpec(name=jobs.RECONCILE_TASK, func=jobs.reconcile, periodic=settings.reconcile_cron))
        return specs

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("groups.create", "{actor} created the group {group} ({count} members)"),
            AuditActionDecl("groups.update", "{actor} changed the group {group} ({change})"),
            AuditActionDecl("groups.delete", "{actor} deleted the group {group} ({count} members)"),
            AuditActionDecl("groups.members.add", "{actor} added {person} to {group} as {role}"),
            AuditActionDecl("groups.members.remove", "{actor} removed {person} from {group}"),
            AuditActionDecl("scim.users.create", "{actor} provisioned {person} ({email})"),
            AuditActionDecl("scim.users.update", "{actor} updated {person} ({change})"),
            AuditActionDecl("scim.users.deactivate", "{actor} deactivated {person}: sessions ended, access removed"),
            AuditActionDecl("scim.users.reactivate", "{actor} reactivated {person}"),
            AuditActionDecl("scim.users.delete", "{actor} deleted {person}: sessions ended, access removed"),
            AuditActionDecl("scim.groups.create", "{actor} created the group {group} ({count} members)"),
            AuditActionDecl("scim.groups.update", "{actor} updated the group {group} (+{added} -{removed} members)"),
            AuditActionDecl("scim.groups.delete", "{actor} deleted the group {group} ({count} members)"),
            AuditActionDecl(
                "directory.users.deprovision", "{actor} deprovisioned {person}: sessions ended, access removed"
            ),
            AuditActionDecl("directory.scim.token.create", "{actor} created the SCIM token {label}"),
            AuditActionDecl("directory.scim.token.rotate", "{actor} rotated the SCIM token {label}"),
            AuditActionDecl("directory.scim.token.revoke", "{actor} revoked the SCIM token {label} ({prefix}…)"),
            AuditActionDecl("directory.mapping.create", "{actor} mapped the IdP group {idp_group} to {group}"),
            AuditActionDecl("directory.mapping.delete", "{actor} removed the mapping of {idp_group} to {group}"),
            AuditActionDecl("directory.settings.update", "{actor} changed directory sync ({change})"),
            AuditActionDecl("directory.google.update", "{actor} changed Google Workspace sync ({change})"),
            AuditActionDecl("directory.google.sync", "{actor} ran the Google Workspace sync ({outcome})"),
        )
