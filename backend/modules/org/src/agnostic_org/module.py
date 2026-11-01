"""Module declaration: the org (profile, members, invitations, first-run bootstrap)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec, ScopeDecl
from agnostic_org.api.router import invitations_router, members_router, onboarding_router, org_router
from agnostic_org.infrastructure.tables import OrgBase
from agnostic_org.providers import OrgProvider


class OrgModule(BaseModule):
    name = "org"
    version = "0.1.0"
    depends_on = ("identity", "settings", "audit")

    def provide(self) -> Iterable[Provider]:
        return (OrgProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=org_router, prefix="/org", tags=("org",)),
            RouterSpec(router=members_router, prefix="/members", tags=("members",)),
            RouterSpec(router=invitations_router, prefix="/invitations", tags=("invitations",)),
            RouterSpec(router=onboarding_router, prefix="/onboarding", tags=("onboarding",)),
        )

    def metadata(self) -> MetaData | None:
        return OrgBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("org:read", "See the org profile"),
            ScopeDecl("org:write", "Change the org profile and settings"),
            ScopeDecl("org:delete", "Delete the org and transfer ownership"),
            ScopeDecl("org:members:read", "See members and invitations"),
            ScopeDecl("org:members:write", "Invite people, change org roles, remove members"),
            ScopeDecl("org:roles:read", "See access roles and bindings"),
            ScopeDecl("org:roles:write", "Change access roles and bindings"),
            ScopeDecl("org:roles:delete", "Delete access roles"),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("org.bootstrap", "The org {name} was set up"),
            AuditActionDecl("org.update", "{actor} changed the org profile: {keys}"),
            AuditActionDecl("members.join", "{actor} joined the org ({via})"),
            AuditActionDecl("members.update", "{actor} changed {resource}'s org role from {before} to {after}"),
            AuditActionDecl("members.remove", "{actor} removed {resource} from the org"),
            AuditActionDecl("invitations.create", "{actor} invited {email} as {role}"),
            AuditActionDecl("invitations.resend", "{actor} resent the invitation to {email}"),
            AuditActionDecl("invitations.revoke", "{actor} revoked the invitation to {email}"),
            AuditActionDecl("invitations.accept", "{actor} accepted the invitation and joined as {role}"),
        )
