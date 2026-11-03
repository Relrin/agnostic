"""Temporary access: requests, approvals, direct grants and the expiry sweep.

Approvers are whoever can change bindings (``org:roles:write``: Owners and Administrators) plus the owners of any
group that already grants the requested access on that instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from agnostic_access.application.use_cases import WRITE, CreateBinding, NewBinding
from agnostic_access.domain.requests import (
    REQUEST_ID_PREFIX,
    AccessRequest,
    InvalidRequestError,
    RequestStatus,
    check_duration,
    check_reason,
)
from agnostic_access.domain.roles import Binding
from agnostic_access.domain.scopes import satisfies
from agnostic_audit.facade import AuditEntry, actor_of
from agnostic_kernel.auth import SYSTEM_PRINCIPAL, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import bump_access_generation
from agnostic_kernel.errors import ForbiddenError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id

REQUEST_CREATED = "access.request_created"
REQUEST_DECIDED = "access.request_decided"
"""Domain events: a temporary access request was made / decided (notifications reach approvers / the requester)."""


@dataclass(frozen=True, slots=True)
class RequestView:
    request: AccessRequest
    can_decide: bool


class TemporaryAccess(CreateBinding):
    async def request(
        self,
        principal: Principal,
        *,
        instance_ref: str | None,
        role_id: str | None,
        scopes: tuple[str, ...],
        reason: str,
        duration_hours: int,
    ) -> AccessRequest:
        if principal.kind != "user" or await self.c.org.member(principal.id) is None:
            raise ForbiddenError("Only members of the org can ask for access.")
        instance = await self._instance(instance_ref) if instance_ref else None
        role = await self.role(role_id) if role_id else None
        if role is None and not scopes:
            raise ValidationFailedError("Ask for a role or at least one scope.")
        unknown = [scope for scope in scopes if not self.c.evaluator.catalog.known(scope)]
        if unknown:
            raise ValidationFailedError(f"Unknown scopes: {', '.join(unknown)}.")
        try:
            hours = check_duration(duration_hours, max_hours=await self._max_hours())
            cleaned = check_reason(reason)
        except InvalidRequestError as exc:
            raise ValidationFailedError(str(exc)) from exc
        request = AccessRequest(
            id=new_id(REQUEST_ID_PREFIX),
            requester_id=principal.id,
            instance_id=instance.id if instance else None,
            role_id=role.id if role else None,
            scopes=tuple(sorted(set(scopes))),
            reason=cleaned,
            duration_hours=hours,
            status="pending",
            created_at=utcnow(),
        )
        await self.c.requests.add(request)
        await self._audit(principal, "access.requests.create", request)
        await self.c.bindings.commit()
        await self.c.events.publish(
            REQUEST_CREATED,
            {**await self._payload(request), "approver_ids": await self.approvers(request)},
        )
        return request

    async def list(self, principal: Principal, *, status: RequestStatus | None, mine: bool) -> list[RequestView]:
        requests = await self.c.requests.list(status=status, requester_id=principal.id if mine else None)
        admin = (await self.c.authorizer.check(principal, WRITE)).allowed
        views: list[RequestView] = []
        for request in requests:
            can_decide = (
                request.open
                and request.requester_id != principal.id
                and (admin or principal.id in await self.approvers(request))
            )
            if mine or admin or can_decide or request.requester_id == principal.id:
                views.append(RequestView(request, can_decide))
        return views

    async def approve(self, principal: Principal, request_id: str, *, note: str | None) -> AccessRequest:
        request = await self._decidable(principal, request_id)
        now = utcnow()
        binding = await self.build(
            NewBinding(
                user_id=request.requester_id,
                instance_ref=request.instance_id,
                role_id=request.role_id,
                scopes=request.scopes,
                expires_at=now + timedelta(hours=request.duration_hours),
                reason=f"Temporary access: {request.reason}",
            ),
            created_by=principal.id,
        )
        try:
            approved = request.approve(by=principal.id, at=now, binding_id=binding.id, note=note)
        except InvalidRequestError as exc:
            raise ValidationFailedError(str(exc)) from exc
        await self.c.bindings.add(binding)
        await self.c.requests.save(approved)
        await self.audit_binding(principal, "bindings.create", binding)
        await self._audit(principal, "access.requests.approve", approved)
        await self.c.bindings.commit()
        await bump_access_generation(self.c.store)
        await self.announce_privileged(principal, binding)
        await self.c.events.publish(REQUEST_DECIDED, await self._payload(approved, decided_by=principal))
        return approved

    async def deny(self, principal: Principal, request_id: str, *, note: str | None) -> AccessRequest:
        request = await self._decidable(principal, request_id)
        try:
            denied = request.deny(by=principal.id, at=utcnow(), note=note)
        except InvalidRequestError as exc:
            raise ValidationFailedError(str(exc)) from exc
        await self.c.requests.save(denied)
        await self._audit(principal, "access.requests.deny", denied)
        await self.c.bindings.commit()
        await self.c.events.publish(REQUEST_DECIDED, await self._payload(denied, decided_by=principal))
        return denied

    async def cancel(self, principal: Principal, request_id: str) -> AccessRequest:
        request = await self._get(request_id)
        try:
            cancelled = request.cancel(by=principal.id, at=utcnow())
        except InvalidRequestError as exc:
            raise ValidationFailedError(str(exc)) from exc
        await self.c.requests.save(cancelled)
        await self._audit(principal, "access.requests.cancel", cancelled)
        await self.c.bindings.commit()
        return cancelled

    async def grant_temporary(self, principal: Principal, request: NewBinding, *, duration_hours: int) -> Binding:
        """An admin grants temporary access directly ("Grant temporary access…" in the audit log)."""
        _ = await self.c.authorizer.require(principal, WRITE)
        try:
            hours = check_duration(duration_hours, max_hours=await self._max_hours())
            reason = check_reason(request.reason or "")
        except InvalidRequestError as exc:
            raise ValidationFailedError(str(exc)) from exc
        return await self.grant(
            principal,
            NewBinding(
                user_id=request.user_id,
                instance_ref=request.instance_ref,
                role_id=request.role_id,
                scopes=request.scopes,
                expires_at=utcnow() + timedelta(hours=hours),
                reason=f"Temporary access: {reason}",
                principal_kind=request.principal_kind,
            ),
        )

    async def expire(self) -> int:
        """Remove bindings past their expiry and close the requests that created them (the periodic sweep)."""
        now = utcnow()
        expired = await self.c.bindings.expired(now)
        if not expired:
            return 0
        requests = {
            request.binding_id: request for request in await self.c.requests.by_binding([b.id for b in expired])
        }
        for binding in expired:
            await self.c.bindings.delete(binding.id)
            await self.audit_binding(SYSTEM_PRINCIPAL, "bindings.expire", binding)
            request = requests.get(binding.id)
            if request is not None and request.status == "approved":
                await self.c.requests.save(request.expire())
        await self.c.bindings.commit()
        await bump_access_generation(self.c.store)
        return len(expired)

    async def approvers(self, request: AccessRequest) -> list[str]:
        found = set(await self.c.evaluator.holders(None, scope=WRITE))
        wanted = set(request.scopes)
        if request.role_id is not None:
            role = await self.role(request.role_id)
            wanted |= set(role.scopes())
        roles = {role.id: role for role in await self.c.evaluator.roles()}
        for binding in await self.c.bindings.list(principal_kind="group"):
            if binding.instance_id not in {None, request.instance_id} or not binding.active(utcnow()):
                continue
            granted = set(binding.scopes)
            if binding.role_id in roles:
                granted |= roles[binding.role_id].scopes()
            covers = binding.role_id == request.role_id if request.role_id else False
            covers = covers or all(any(satisfies(held, scope) for held in granted) for scope in wanted)
            if covers:
                found.update(await self.c.directory.owners_of(binding.principal_id))
        found.discard(request.requester_id)
        return sorted(found)

    async def _decidable(self, principal: Principal, request_id: str) -> AccessRequest:
        request = await self._get(request_id)
        if request.requester_id == principal.id:
            raise ForbiddenError("You can't decide your own request.")
        admin = (await self.c.authorizer.check(principal, WRITE)).allowed
        if not admin and principal.id not in await self.approvers(request):
            raise ForbiddenError(
                "Only Owners, Administrators and owners of a group with that access can decide this request."
            )
        return request

    async def _get(self, request_id: str) -> AccessRequest:
        request = await self.c.requests.get(request_id)
        if request is None:
            raise NotFoundError(f"There is no access request {request_id}.")
        return request

    async def _max_hours(self) -> int:
        return (await self.c.settings.get()).temporary_access_max_hours

    async def _describe(self, request: AccessRequest) -> tuple[str, str, str]:
        user = await self.c.identity.get_user(request.requester_id)
        instance = await self.c.instances.get(request.instance_id) if request.instance_id else None
        role = await self.role(request.role_id) if request.role_id else None
        grant = role.name if role else ", ".join(request.scopes)
        if role is not None and request.scopes:
            grant += " + " + ", ".join(request.scopes)
        return (
            user.display_name if user else request.requester_id,
            grant,
            instance.display_name if instance else "all instances",
        )

    async def _payload(self, request: AccessRequest, *, decided_by: Principal | None = None) -> dict[str, object]:
        who, grant, where = await self._describe(request)
        return {
            "request_id": request.id,
            "requester_id": request.requester_id,
            "requester_name": who,
            "grant": grant,
            "where": where,
            "instance_id": request.instance_id,
            "reason": request.reason,
            "duration_hours": request.duration_hours,
            "status": request.status,
            "decided_by": decided_by.id if decided_by else None,
            "decided_by_name": decided_by.display_name if decided_by else None,
            "note": request.note,
            "expires_at": request.expires_at.isoformat() if request.expires_at else None,
        }

    async def _audit(self, principal: Principal, action: str, request: AccessRequest) -> None:
        who, grant, where = await self._describe(request)
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="access_request",
                resource_id=request.id,
                resource_display=f"{grant} on {where} for {who}",
                instance_id=request.instance_id,
                fields={
                    "person": who,
                    "grant": grant,
                    "where": where,
                    "hours": str(request.duration_hours),
                },
                diff={
                    "title": "Temporary access",
                    "lines": [{"op": "note", "text": f"Reason: {request.reason}"}]
                    + ([{"op": "note", "text": f"Note: {request.note}"}] if request.note else []),
                    "note": f"For {request.duration_hours} h",
                },
                links={"requests": "/access/people?tab=requests"},
            )
        )
