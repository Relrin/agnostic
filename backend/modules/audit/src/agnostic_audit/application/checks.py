"""The archive bucket for ``agnostic config check --connect``: reachable, and the credentials accepted."""

from __future__ import annotations

import asyncio

from agnostic_audit.application.policy import PolicyService
from agnostic_audit.application.ports import ObjectNotFoundError, ObjectStores
from agnostic_audit.domain.archive import object_keys
from agnostic_kernel.diagnostics import CheckResult

CHECK_TIMEOUT = 10.0


async def archive_checks(policies: PolicyService, stores: ObjectStores) -> list[CheckResult]:
    target = await policies.target()
    if target is None:
        return []
    facts = {"endpoint": target.endpoint, "bucket": target.bucket, "object_lock": target.object_lock_mode}
    probe, _ = object_keys(target.prefix, "0000-01")  # never written: a 404 proves access without writing
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            _ = await stores.open(target).head(probe)
    except ObjectNotFoundError:
        return [CheckResult("audit archive", ok=True, detail="reachable", facts=facts)]
    except Exception as exc:  # noqa: BLE001  (unreachable, refused credentials, TLS)
        return [CheckResult("audit archive", ok=False, detail=str(exc) or type(exc).__name__, facts=facts)]
    return [CheckResult("audit archive", ok=True, detail="reachable", facts=facts)]
