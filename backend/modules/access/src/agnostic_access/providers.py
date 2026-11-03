"""Dependency wiring of the access module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_access.application.evaluator import AccessAuthorizer, AccessEvaluator, ScopeCatalog
from agnostic_access.application.ports import BindingRepository, CatalogRepository, RequestRepository, RoleRepository
from agnostic_access.application.requests import TemporaryAccess
from agnostic_access.application.roles import RoleEditor
from agnostic_access.application.use_cases import (
    AccessContext,
    CreateBinding,
    DeleteBinding,
    Explain,
    GetMyAccess,
    InvitationBindings,
    ListBindings,
    ListRoles,
    ListScopes,
    RevokePrincipal,
    SyncCatalog,
)
from agnostic_access.facade import AccessFacade, AccessFacadeImpl
from agnostic_access.infrastructure.repository import (
    SqlBindingRepository,
    SqlCatalogRepository,
    SqlRequestRepository,
    SqlRoleRepository,
)
from agnostic_directory.facade import AccessRevoker
from agnostic_kernel.auth import Authorizer
from agnostic_org.facade import InitialBindingsApplier


class AccessProvider(Provider):
    scope = Scope.REQUEST

    roles = provide(SqlRoleRepository, provides=RoleRepository)
    bindings = provide(SqlBindingRepository, provides=BindingRepository)
    requests = provide(SqlRequestRepository, provides=RequestRepository)
    catalog_repository = provide(SqlCatalogRepository, provides=CatalogRepository)
    catalog = provide(ScopeCatalog, scope=Scope.APP)
    evaluator = provide(AccessEvaluator)
    authorizer = provide(AccessAuthorizer, provides=Authorizer)
    facade = provide(AccessFacadeImpl, provides=AccessFacade)
    context = provide(AccessContext)

    list_roles = provide(ListRoles)
    list_scopes = provide(ListScopes)
    list_bindings = provide(ListBindings)
    create_binding = provide(CreateBinding)
    delete_binding = provide(DeleteBinding)
    my_access = provide(GetMyAccess)
    explain = provide(Explain)
    sync = provide(SyncCatalog)
    role_editor = provide(RoleEditor)
    temporary_access = provide(TemporaryAccess)
    invitation_bindings = provide(InvitationBindings, provides=InitialBindingsApplier)
    revoker = provide(RevokePrincipal, provides=AccessRevoker)
