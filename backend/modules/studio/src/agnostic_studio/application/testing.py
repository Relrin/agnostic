"""Test a draft from the editor or the workflow builder.

AgentOS runs draft versions only for their owner or an admin, so Studio elevates.

The person must hold ``components:write`` (the justification) and may run the component; the run itself is one
streamed request with a single-use admin token whose ``sub`` is still the person, audited as ``gateway.elevated``.
"""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_gateway.facade import ElevatedStream
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import ValidationFailedError
from agnostic_studio.application.access import READ_SCOPE, WRITE_SCOPE, StudioAccess
from agnostic_studio.application.components import Reader
from agnostic_studio.application.ports import StudioStore
from agnostic_studio.domain.model import FAMILY

MAX_MESSAGE = 20_000


@dataclass(frozen=True, slots=True)
class TestRun:
    message: str
    version: int
    session_id: str | None = None


class DraftRuns:
    def __init__(self, access: StudioAccess, store: StudioStore) -> None:
        self._access = access
        self._reader = Reader(access, store)

    async def open(self, principal: Principal, ref: str, component_id: str, run: TestRun) -> ElevatedStream:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        if not run.message.strip() or len(run.message) > MAX_MESSAGE:
            raise ValidationFailedError("Write a message to send (up to 20,000 characters).")
        family = FAMILY[component.kind]
        await self._access.require(principal, f"{family}:{component_id}:run", instance)
        form = {"message": run.message, "stream": "true", "version": str(run.version)}
        if run.session_id:
            form["session_id"] = run.session_id
        return await self._access.gateway.elevated_stream(
            principal,
            instance,
            "POST",
            f"/{family}/{component_id}/runs",
            justification=WRITE_SCOPE,
            action_label="test drafts",
            form=form,
        )
