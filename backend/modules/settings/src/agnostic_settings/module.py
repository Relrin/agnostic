"""Module declaration: org-wide settings."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, ScopeDecl
from agnostic_settings.infrastructure.tables import SettingsBase
from agnostic_settings.providers import SettingsProvider


class SettingsModule(BaseModule):
    name = "settings"
    version = "0.4.1"
    depends_on = ("audit",)

    def provide(self) -> Iterable[Provider]:
        return (SettingsProvider(),)

    def metadata(self) -> MetaData | None:
        return SettingsBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("settings:read", "See org settings"),
            ScopeDecl("settings:write", "Change org settings"),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (AuditActionDecl("settings.org.update", "{actor} changed org settings: {keys}"),)
