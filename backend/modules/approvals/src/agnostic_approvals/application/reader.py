"""Reading approvals from AgentOS as the control plane.

Under user isolation AgentOS shows a non-admin only their own approvals, so an operator's inbox would be empty. The
inbox therefore reads as the control plane, after checking ``approvals:read`` itself, the same way the pending-count
badge does. Resolving still goes through the person (delegated elevation).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from agnostic_agentos_client import AgentOSError, CapabilityDisabledError, InstanceUnreachableError, NotFoundError
from agnostic_approvals.domain.inbox import ApprovalRecord
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.errors import AppError, ServiceUnavailableError

PAGE_SIZE = 100


class ApprovalsUnavailableError(AppError):
    status = 502
    code = "approvals_unavailable"
    title = "The instance didn't answer the approvals request"


def page_items(payload: object) -> tuple[list[dict[str, Any]], int | None]:
    if isinstance(payload, list):
        items = cast("list[Any]", payload)
        return [cast("dict[str, Any]", item) for item in items if isinstance(item, dict)], len(items)
    if isinstance(payload, dict):
        body = cast("dict[str, Any]", payload)
        data = cast("list[Any]", body.get("data") or [])
        total = cast("dict[str, Any]", body.get("meta") or {}).get("total_count")
        return [cast("dict[str, Any]", item) for item in data if isinstance(item, dict)], (
            int(total) if isinstance(total, int | float) else None
        )
    return [], None


class ApprovalsReader:
    def __init__(self, instances: InstancesFacade) -> None:
        self._instances = instances

    async def _get(self, instance: Instance, path: str, params: Mapping[str, str | int] | None = None) -> Any:  # noqa: ANN401
        try:
            return await self._instances.system_call(instance, "GET", path, params=params)
        except CapabilityDisabledError as exc:
            raise ServiceUnavailableError(f"Approvals are turned off on {instance.display_name}.") from exc
        except InstanceUnreachableError as exc:
            raise ApprovalsUnavailableError(f"{instance.display_name} is unreachable: {exc}") from exc

    async def total(self, instance: Instance, params: Mapping[str, str | int]) -> int:
        _, total = page_items(await self._get(instance, "/approvals", {**params, "limit": 1, "page": 1}))
        return total or 0

    async def scan(
        self, instance: Instance, params: Mapping[str, str | int], cap: int
    ) -> tuple[list[ApprovalRecord], bool]:
        """Newest approvals matching ``params``, at most ``cap``; the flag says whether more exist."""
        records: list[ApprovalRecord] = []
        page = 1
        while len(records) < cap:
            items, total = page_items(
                await self._get(instance, "/approvals", {**params, "limit": PAGE_SIZE, "page": page})
            )
            records.extend(ApprovalRecord.parse(item) for item in items)
            if len(items) < PAGE_SIZE or (total is not None and page * PAGE_SIZE >= total):
                return records[:cap], len(records) > cap
            page += 1
        return records[:cap], True

    async def get(self, instance: Instance, approval_id: str) -> ApprovalRecord | None:
        try:
            body = await self._instances.system_call(instance, "GET", f"/approvals/{approval_id}")
        except NotFoundError:
            return None
        except CapabilityDisabledError as exc:
            raise ServiceUnavailableError(f"Approvals are turned off on {instance.display_name}.") from exc
        except AgentOSError as exc:
            raise ApprovalsUnavailableError(f"{instance.display_name}: {exc}") from exc
        return ApprovalRecord.parse(cast("dict[str, Any]", body)) if isinstance(body, dict) else None

    async def run(self, instance: Instance, record: ApprovalRecord) -> dict[str, Any] | None:
        """The paused run (input, messages, status); ``None`` when the instance can't say."""
        component = record.component
        if not record.run_id or not record.session_id or component is None:
            return None
        try:
            body = await self._instances.system_call(
                instance,
                "GET",
                f"/sessions/{record.session_id}/runs/{record.run_id}",
                params={"type": component[0]},
            )
        except AgentOSError:
            return None
        return cast("dict[str, Any]", body) if isinstance(body, dict) else None
