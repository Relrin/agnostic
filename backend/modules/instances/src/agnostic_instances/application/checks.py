"""Runtime reachability for ``agnostic config check --connect`` and the System page."""

from __future__ import annotations

import asyncio

from agnostic_instances.application.ports import InstanceRepository, RuntimeClient, Target
from agnostic_instances.domain.instances import Instance, InstanceStatus
from agnostic_kernel.diagnostics import CheckResult

CHECK_TIMEOUT = 5.0


async def _check(client: RuntimeClient, instance: Instance) -> CheckResult:
    name = f"instance {instance.slug}"
    facts = {
        "endpoint": instance.endpoint_url,
        "tls": "mutual" if instance.has_client_certificate else ("verified" if instance.tls_verify else "unverified"),
        "network": instance.network_mode.value,
    }
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            latency = await client.health(Target.of(instance))
    except Exception as exc:  # noqa: BLE001  (any failure is the answer: unreachable, TLS, refused)
        return CheckResult(name, ok=False, detail=f"unreachable: {exc or type(exc).__name__}", facts=facts)
    return CheckResult(name, ok=True, detail="reachable", facts={**facts, "latency_ms": f"{latency:.0f}"})


async def instance_checks(instances: InstanceRepository, client: RuntimeClient) -> list[CheckResult]:
    enabled = [item for item in await instances.list() if item.status is not InstanceStatus.DISABLED]
    return list(await asyncio.gather(*(_check(client, item) for item in enabled)))
