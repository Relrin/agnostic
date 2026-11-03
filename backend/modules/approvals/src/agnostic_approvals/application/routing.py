"""Approval routing rules, who an approval reaches, and each instance's expiry policy.

Routing is advisory: it decides who gets told, not who may resolve (that stays ``approvals:write`` through AgentOS).
A rule names members, groups and access roles; members of a named group and people holding a named role on the
instance are included. Routed people who
can't read approvals there are left out, so a notification never points at a page someone can't open.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from agnostic_access.facade import AccessFacade
from agnostic_approvals.application.ports import ApprovalStore, Policy, RouteDraft
from agnostic_approvals.domain.inbox import ApprovalRecord, Route, matching_routes
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_directory.facade import DirectoryFacade
from agnostic_gateway.facade import GatewayFacade
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import NotFoundError, ValidationFailedError

READ = "approvals:read"
WRITE = "approvals:write"
ORG_WRITE = "settings:write"
MEMBERS_READ = "org:members:read"
ADMIN = "agent_os:admin"
PERSONAL_CHANNELS = ("in_app", "email", "slack")
MAX_TTL_HOURS = 24 * 30


@dataclass(frozen=True, slots=True)
class RouteView:
    route: Route
    member_names: dict[str, str]
    role_names: dict[str, str]
    group_names: dict[str, str]


@dataclass(frozen=True, slots=True)
class Recipients:
    user_ids: list[str]
    routed_to: list[str]
    """Route names ("Billing ops"), what the timeline says the approval was routed to."""
    channels: list[str]
    """Personal channels the routes add (``slack``, ``email``)."""
    channel_ids: list[str]
    """Org notification channels named by the routes."""


class ApprovalRouting:
    def __init__(
        self,
        gateway: GatewayFacade,
        authorizer: Authorizer,
        store: ApprovalStore,
        access: AccessFacade,
        identity: IdentityFacade,
        audit: AuditLog,
        directory: DirectoryFacade,
    ) -> None:
        self._directory = directory
        self._gateway = gateway
        self._authorizer = authorizer
        self._store = store
        self._access = access
        self._identity = identity
        self._audit = audit

    async def _views(self, routes: Sequence[Route]) -> list[RouteView]:
        ids = sorted({member for route in routes for member in route.member_ids})
        members = {user.id: user.display_name for user in await self._identity.get_users(ids)}
        roles = await self._access.role_names()
        groups = {group.id: group.name for group in await self._directory.groups()}
        return [
            RouteView(
                route,
                {member: members.get(member, member) for member in route.member_ids},
                {role: roles.get(role, role) for role in route.role_ids},
                {group: groups.get(group, group) for group in route.group_ids},
            )
            for route in routes
        ]

    async def for_group(self, principal: Principal, group_id: str) -> list[RouteView]:
        """Routes naming a group, on every instance: "Approvals routed here" on the group."""
        _ = await self._authorizer.require(principal, MEMBERS_READ)
        return await self._views([route for route in await self._store.all_routes() if group_id in route.group_ids])

    async def list(self, principal: Principal, instance_ref: str | None) -> list[RouteView]:
        if instance_ref is None:
            _ = await self._authorizer.require(principal, ORG_WRITE)
            return await self._views(await self._store.routes(None))
        instance = await self._gateway.instance(instance_ref)
        _ = await self._authorizer.require(principal, READ, instance_id=instance.id)
        return await self._views(await self._store.routes(instance.id))

    async def _check(self, principal: Principal, instance_id: str | None) -> None:
        if instance_id is None:
            _ = await self._authorizer.require(principal, ORG_WRITE)
        else:
            _ = await self._authorizer.require(principal, WRITE, instance_id=instance_id)

    async def _validated(self, draft: RouteDraft) -> RouteDraft:
        name = draft.name.strip()
        if not name:
            raise ValidationFailedError("A route needs a name, e.g. the team it reaches.")
        if not draft.member_ids and not draft.role_ids and not draft.group_ids:
            raise ValidationFailedError("A route needs at least one member, group or role.")
        unknown = [channel for channel in draft.channels if channel not in PERSONAL_CHANNELS]
        if unknown:
            raise ValidationFailedError(f"Unknown channels: {', '.join(unknown)}.")
        roles = await self._access.role_names()
        missing = [role for role in draft.role_ids if role not in roles]
        if missing:
            raise ValidationFailedError(f"Unknown access roles: {', '.join(missing)}.")
        found = {user.id for user in await self._identity.get_users(list(draft.member_ids))}
        absent = [member for member in draft.member_ids if member not in found]
        if absent:
            raise ValidationFailedError(f"Unknown members: {', '.join(absent)}.")
        known = {group.id for group in await self._directory.groups()}
        unknown_groups = [group for group in draft.group_ids if group not in known]
        if unknown_groups:
            raise ValidationFailedError(f"Unknown groups: {', '.join(unknown_groups)}.")
        return replace(draft, name=name, channels=tuple(c for c in PERSONAL_CHANNELS if c in draft.channels))

    async def create(self, principal: Principal, instance_ref: str | None, draft: RouteDraft) -> RouteView:
        instance = await self._gateway.instance(instance_ref) if instance_ref else None
        draft = await self._validated(replace(draft, instance_id=instance.id if instance else None))
        await self._check(principal, draft.instance_id)
        route = await self._store.add_route(draft, created_by=principal.id)
        await self._record(principal, "approvals.route.created", route, instance)
        await self._store.commit()
        return (await self._views([route]))[0]

    async def _existing(self, principal: Principal, route_id: str) -> tuple[Route, Instance | None]:
        route = await self._store.route(route_id)
        if route is None:
            raise NotFoundError(f"There is no approval route {route_id!r}.")
        await self._check(principal, route.instance_id)
        instance = await self._gateway.instance(route.instance_id) if route.instance_id else None
        return route, instance

    async def update(self, principal: Principal, route_id: str, draft: RouteDraft) -> RouteView:
        current, instance = await self._existing(principal, route_id)
        route = await self._store.update_route(
            route_id, await self._validated(replace(draft, instance_id=current.instance_id))
        )
        await self._record(principal, "approvals.route.updated", route, instance)
        await self._store.commit()
        return (await self._views([route]))[0]

    async def delete(self, principal: Principal, route_id: str) -> None:
        route, instance = await self._existing(principal, route_id)
        await self._store.delete_route(route_id)
        await self._record(principal, "approvals.route.deleted", route, instance)
        await self._store.commit()

    async def _record(self, principal: Principal, action: str, route: Route, instance: Instance | None) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="approval_route",
                resource_id=route.id,
                resource_display=route.name,
                instance_id=route.instance_id,
                scope_checked=WRITE if route.instance_id else ORG_WRITE,
                fields={
                    "route": route.name,
                    "tool": route.tool_name or "any tool",
                    "where": instance.display_name if instance else "all instances",
                },
            )
        )

    async def recipients(self, instance_id: str, record: ApprovalRecord) -> Recipients:
        routes = matching_routes(await self._store.routes(instance_id), record, instance_id)
        readers = set(await self._access.holders(instance_id, scope=READ))
        if not routes:
            deciders = await self._access.holders(instance_id, scope=WRITE)
            return Recipients(user_ids=sorted(set(deciders) & readers), routed_to=[], channels=[], channel_ids=[])
        users: set[str] = set()
        for route in routes:
            users.update(route.member_ids)
            if route.role_ids:
                users.update(await self._access.holders(instance_id, role_ids=route.role_ids))
            for group_id in route.group_ids:
                users.update(await self._directory.members_of(group_id))
        return Recipients(
            user_ids=sorted(users & readers),
            routed_to=[route.name for route in routes],
            channels=sorted({channel for route in routes for channel in route.channels}),
            channel_ids=sorted({channel for route in routes for channel in route.channel_ids}),
        )

    async def policy(self, principal: Principal, instance_ref: str) -> tuple[Instance, Policy]:
        instance = await self._gateway.instance(instance_ref)
        _ = await self._authorizer.require(principal, READ, instance_id=instance.id)
        return instance, await self._store.policy(instance.id)

    async def set_policy(
        self, principal: Principal, instance_ref: str, *, enforce_expiry: bool, ttl_hours: int | None
    ) -> tuple[Instance, Policy]:
        instance = await self._gateway.instance(instance_ref)
        _ = await self._authorizer.require(principal, ADMIN, instance_id=instance.id)
        if ttl_hours is not None and not 0 <= ttl_hours <= MAX_TTL_HOURS:
            raise ValidationFailedError(f"ttl_hours must be between 0 and {MAX_TTL_HOURS}.")
        before = await self._store.policy(instance.id)
        policy = await self._store.set_policy(
            Policy(instance.id, enforce_expiry=enforce_expiry, ttl_hours=ttl_hours, updated_by=principal.id)
        )
        _ = await self._audit.record(
            AuditEntry(
                action="approvals.policy.updated",
                actor=actor_of(principal),
                resource_kind="approval_policy",
                resource_id=instance.id,
                resource_display=instance.display_name,
                instance_id=instance.id,
                scope_checked=ADMIN,
                fields={
                    "instance": instance.display_name,
                    "state": "enforced" if enforce_expiry else "not enforced",
                },
                diff={
                    "enforce_expiry": {"before": before.enforce_expiry, "after": enforce_expiry},
                    "ttl_hours": {"before": before.ttl_hours, "after": ttl_hours},
                },
            )
        )
        await self._store.commit()
        return instance, policy
