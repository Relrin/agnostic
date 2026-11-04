"""Sign-in providers for ``agnostic config check --connect``: every enabled OIDC issuer answers discovery."""

from __future__ import annotations

import asyncio

from agnostic_identity.application.ports import SignInClients
from agnostic_identity.infrastructure.signin_clients import OidcClient
from agnostic_kernel.diagnostics import CheckResult

CHECK_TIMEOUT = 5.0


async def provider_checks(clients: SignInClients) -> list[CheckResult]:
    results: list[CheckResult] = []
    for config in await clients.all():
        client = await clients.get(config.id)
        if not isinstance(client, OidcClient):
            continue
        name = f"sign-in {config.id}"
        try:
            async with asyncio.timeout(CHECK_TIMEOUT):
                endpoint = await client.check()
        except Exception as exc:  # noqa: BLE001  (the probe reports, sign-in itself raises)
            results.append(CheckResult(name, ok=False, detail=str(exc) or type(exc).__name__))
            continue
        results.append(CheckResult(name, ok=True, detail="discovery ok", facts={"issuer": config.issuer or ""}))
        if endpoint and not endpoint.startswith("https://"):
            results[-1].facts["warning"] = "authorization endpoint is not https"
    return results
