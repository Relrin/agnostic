"""The only import surface other modules may use: look up instances and mint tokens for them.

Private keys never leave this module: callers get signed tokens, not keys.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any, Protocol

from agnostic_instances.application.diagnostics import RuntimeAuth
from agnostic_instances.application.ports import InstanceRepository, RuntimeClient, Target
from agnostic_instances.application.tokens import MintedToken, TokenService
from agnostic_instances.domain.instances import AuthMode, EnvTag, Instance, InstanceStatus, SubClaimMode
from agnostic_kernel.crypto import SecretBox

__all__ = [
    "AuthMode",
    "EnvTag",
    "Instance",
    "InstanceStatus",
    "InstancesFacade",
    "InstancesFacadeImpl",
    "MintedToken",
    "SubClaimMode",
]


class InstancesFacade(Protocol):
    async def get(self, ref: str) -> Instance | None:
        """By id or slug."""
        ...

    async def list(self) -> list[Instance]: ...
    async def mint(
        self,
        instance: Instance,
        *,
        subject: str,
        scopes: Sequence[str],
        name: str | None,
        via: str = "gateway",
        ttl: timedelta | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> MintedToken: ...
    async def security_key(self, instance: Instance) -> str | None:
        """The ``OS_SECURITY_KEY`` of a security-key instance, decrypted."""
        ...

    async def system_call(
        self,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> Any:  # noqa: ANN401
        """Call the runtime as the control plane itself (``agnostic-system``, ``agent_os:admin``).

        For aggregate, control-plane-owned reads (Home overview, the approvals inbox after its own scope check) and
        control-plane policy actions (expiring approvals); never on behalf of a person.
        Errors are the ``agnostic_agentos_client`` ones.
        """
        ...


class InstancesFacadeImpl:
    def __init__(
        self,
        instances: InstanceRepository,
        tokens: TokenService,
        box: SecretBox,
        auth: RuntimeAuth,
        client: RuntimeClient,
    ) -> None:
        self._instances = instances
        self._tokens = tokens
        self._box = box
        self._auth = auth
        self._client = client

    async def get(self, ref: str) -> Instance | None:
        return await self._instances.get(ref)

    async def list(self) -> list[Instance]:
        return await self._instances.list()

    async def mint(
        self,
        instance: Instance,
        *,
        subject: str,
        scopes: Sequence[str],
        name: str | None,
        via: str = "gateway",
        ttl: timedelta | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> MintedToken:
        return await self._tokens.mint(
            instance, subject=subject, scopes=scopes, name=name, via=via, ttl=ttl, extra=extra
        )

    async def security_key(self, instance: Instance) -> str | None:
        sealed = await self._instances.security_key(instance.id)
        return self._box.open(sealed).decode() if sealed else None

    async def system_call(
        self,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> Any:  # noqa: ANN401
        sealed = await self._instances.security_key(instance.id) if instance.has_security_key else None
        headers = await self._auth.headers(instance, sealed_key=sealed)
        return await self._client.request_json(
            Target.of(instance), method, path, headers, params=params, json=json, form=form
        )
