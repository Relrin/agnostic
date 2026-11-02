"""Learning counts per type, and per-user deletion with type-to-confirm and an audit record.

Deletion runs on one instance, or on every instance for a data-subject request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_context.application.calls import ContextCalls, checked, page_items
from agnostic_context.domain.learnings import LEARNING_TYPES, confirmed, deletion_scope
from agnostic_instances.facade import Instance, InstancesFacade, InstanceStatus
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import AppError, ValidationFailedError

DELETE_SCOPE = "learnings:delete"


class LearningCounts:
    """``GET /learnings?learning_type=…&limit=1`` per type, in parallel; ``None`` where AgentOS didn't answer."""

    def __init__(self, calls: ContextCalls) -> None:
        self._calls = calls

    async def __call__(
        self,
        principal: Principal,
        instance_ref: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        namespace: str | None = None,
        db_id: str | None = None,
    ) -> dict[str, int | None]:
        instance = await self._calls.instance(instance_ref)
        await self._calls.require(principal, "learnings:read", instance)

        async def one(learning_type: str) -> int | None:
            response = await self._calls.call(
                principal,
                instance,
                "GET",
                "/learnings",
                params={
                    "learning_type": learning_type,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "namespace": namespace,
                    "db_id": db_id,
                    "limit": 1,
                    "page": 1,
                },
            )
            return page_items(response.body)[1] if response.ok else None

        counts = await asyncio.gather(*(one(kind) for kind in LEARNING_TYPES))
        return dict(zip(LEARNING_TYPES, counts, strict=True))


@dataclass(frozen=True, slots=True)
class Deletion:
    instance_id: str
    instance: str
    user_id: str
    learning_type: str | None
    deleted: int | None
    """Records counted just before the delete (AgentOS answers 204 without a count)."""


class DeleteUserLearnings:
    """``DELETE /learnings/users/{user_id}`` as the person, after the typed confirmation; audited with the count."""

    def __init__(self, calls: ContextCalls, audit: AuditLog) -> None:
        self._calls = calls
        self._audit = audit

    async def __call__(
        self,
        principal: Principal,
        instance_ref: str,
        user_id: str,
        confirmation: str,
        *,
        learning_type: str | None = None,
        db_id: str | None = None,
    ) -> Deletion:
        if not confirmed(user_id, confirmation):
            raise ValidationFailedError(f"Type {user_id} to confirm.", extra={"field": "confirm"})
        instance = await self._calls.instance(instance_ref)
        return await self.on(principal, instance, user_id, learning_type=learning_type, db_id=db_id)

    async def on(
        self,
        principal: Principal,
        instance: Instance,
        user_id: str,
        *,
        learning_type: str | None = None,
        db_id: str | None = None,
    ) -> Deletion:
        if learning_type is not None and learning_type not in LEARNING_TYPES:
            raise ValidationFailedError(f"Unknown learning type {learning_type}.", extra={"field": "learning_type"})
        await self._calls.require(principal, DELETE_SCOPE, instance)
        before = await self._calls.call(
            principal,
            instance,
            "GET",
            "/learnings",
            params={"user_id": user_id, "learning_type": learning_type, "db_id": db_id, "limit": 1, "page": 1},
        )
        deleted = page_items(before.body)[1] if before.ok else None
        checked(
            instance,
            await self._calls.call(
                principal,
                instance,
                "DELETE",
                f"/learnings/users/{user_id}",
                params={"learning_type": learning_type, "db_id": db_id},
            ),
        )
        _ = await self._audit.record_now(
            AuditEntry(
                action="context.learnings.user_deleted",
                actor=actor_of(principal),
                resource_kind="user_learnings",
                resource_id=user_id,
                resource_display=f"learnings of {user_id}",
                instance_id=instance.id,
                scope_checked=DELETE_SCOPE,
                response_status=204,
                fields={
                    "user": user_id,
                    "types": deletion_scope(learning_type),
                    "count": "?" if deleted is None else str(deleted),
                    "where": instance.display_name,
                },
            )
        )
        return Deletion(instance.id, instance.display_name, user_id, learning_type, deleted)


@dataclass(frozen=True, slots=True)
class InstanceOutcome:
    instance_id: str
    instance: str
    status: Literal["deleted", "skipped", "failed"]
    deleted: int | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class DataSubjectResult:
    user_id: str
    outcomes: Sequence[InstanceOutcome]


class DataSubjectRequest:
    """Delete one person's learnings on every enabled instance where the caller holds ``learnings:delete``."""

    def __init__(
        self, calls: ContextCalls, instances: InstancesFacade, delete: DeleteUserLearnings, audit: AuditLog
    ) -> None:
        self._calls = calls
        self._instances = instances
        self._delete = delete
        self._audit = audit

    async def __call__(self, principal: Principal, user_id: str, confirmation: str) -> DataSubjectResult:
        if not confirmed(user_id, confirmation):
            raise ValidationFailedError(f"Type {user_id} to confirm.", extra={"field": "confirm"})
        outcomes = [await self._one(principal, instance, user_id) for instance in await self._instances.list()]
        counts: Mapping[str, int] = {
            status: sum(1 for outcome in outcomes if outcome.status == status)
            for status in ("deleted", "skipped", "failed")
        }
        _ = await self._audit.record_now(
            AuditEntry(
                action="context.data_subject.requested",
                actor=actor_of(principal),
                resource_kind="data_subject",
                resource_id=user_id,
                resource_display=user_id,
                fields={"user": user_id, **{key: str(value) for key, value in counts.items()}},
                diff={
                    outcome.instance: {"status": outcome.status, "deleted": outcome.deleted, "reason": outcome.reason}
                    for outcome in outcomes
                },
            )
        )
        return DataSubjectResult(user_id, outcomes)

    async def _one(self, principal: Principal, instance: Instance, user_id: str) -> InstanceOutcome:
        def skipped(reason: str) -> InstanceOutcome:
            return InstanceOutcome(instance.id, instance.display_name, "skipped", None, reason)

        if instance.status == InstanceStatus.DISABLED:
            return skipped("The instance is disabled.")
        if not await self._calls.allowed(principal, DELETE_SCOPE, instance):
            return skipped(f"You don't have {DELETE_SCOPE} here.")
        try:
            deletion = await self._delete.on(principal, instance, user_id)
        except AppError as exc:
            return InstanceOutcome(instance.id, instance.display_name, "failed", None, exc.detail or exc.title)
        return InstanceOutcome(instance.id, instance.display_name, "deleted", deletion.deleted, None)
