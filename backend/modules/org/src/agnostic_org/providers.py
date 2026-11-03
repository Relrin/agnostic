"""Dependency wiring of the org module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_audit.facade import AuditLog
from agnostic_identity.facade import IdentityFacade, MembershipDirectory
from agnostic_kernel.auth import Authorizer
from agnostic_kernel.bootstrap import Bootstrapper
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.mail import Mailer
from agnostic_kernel.settings import Settings
from agnostic_org.application.invitations import (
    AcceptInvitation,
    InvitationContext,
    InvitePerson,
    ListInvitations,
    PreviewInvitation,
    ResendInvitation,
    RevokeInvitation,
)
from agnostic_org.application.members import (
    BulkMembers,
    ChangeOrgRole,
    ExportMembers,
    GetMember,
    ListMembers,
    OrgMembershipDirectory,
    RemoveMember,
)
from agnostic_org.application.ports import (
    GroupDirectory,
    InitialBindingsApplier,
    InvitationRepository,
    MemberRepository,
    OrgRepository,
)
from agnostic_org.application.profile import Bootstrap, CompleteOnboarding, GetOrg, OnboardingStatus, UpdateOrg
from agnostic_org.facade import OrgFacade, OrgFacadeImpl
from agnostic_org.infrastructure.repository import SqlInvitationRepository, SqlMemberRepository, SqlOrgRepository


class OrgProvider(Provider):
    scope = Scope.REQUEST

    org = provide(SqlOrgRepository, provides=OrgRepository)
    members = provide(SqlMemberRepository, provides=MemberRepository)
    invitations = provide(SqlInvitationRepository, provides=InvitationRepository)
    directory = provide(OrgMembershipDirectory, provides=MembershipDirectory)
    facade = provide(OrgFacadeImpl, provides=OrgFacade)

    get_org = provide(GetOrg)
    update_org = provide(UpdateOrg)
    onboarding_status = provide(OnboardingStatus)
    list_members = provide(ListMembers)
    get_member = provide(GetMember)
    change_role = provide(ChangeOrgRole)
    remove_member = provide(RemoveMember)
    bulk_members = provide(BulkMembers)
    export_members = provide(ExportMembers)

    @provide
    def bootstrap(
        self,
        org: OrgRepository,
        members: MemberRepository,
        identity: IdentityFacade,
        audit: AuditLog,
        settings: Settings,
    ) -> Bootstrap:
        return Bootstrap(org, members, identity, audit, settings.public_url())

    @provide
    def bootstrapper(self, bootstrap: Bootstrap) -> Bootstrapper:
        return bootstrap

    @provide
    def complete_onboarding(
        self,
        org: OrgRepository,
        members: MemberRepository,
        identity: IdentityFacade,
        audit: AuditLog,
        settings: Settings,
    ) -> CompleteOnboarding:
        return CompleteOnboarding(org, members, identity, audit, settings.public_url())

    invite = provide(InvitePerson)
    resend = provide(ResendInvitation)
    revoke = provide(RevokeInvitation)
    list_invitations = provide(ListInvitations)
    preview = provide(PreviewInvitation)
    accept = provide(AcceptInvitation)

    @provide
    def invitation_context(
        self,
        invitations: InvitationRepository,
        members: MemberRepository,
        org: OrgRepository,
        identity: IdentityFacade,
        bindings: InitialBindingsApplier,
        groups: GroupDirectory,
        authorizer: Authorizer,
        audit: AuditLog,
        mailer: Mailer,
        store: EphemeralStore,
        settings: Settings,
    ) -> InvitationContext:
        return InvitationContext(
            invitations=invitations,
            members=members,
            org=org,
            identity=identity,
            bindings=bindings,
            groups=groups,
            authorizer=authorizer,
            audit=audit,
            mailer=mailer,
            store=store,
            public_url=settings.public_url(),
        )
