"""The only import surface other modules may use: look up instances and mint tokens for them.

Private keys never leave this module: callers get signed tokens, not keys.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from agnostic_instances.application.ports import InstanceRepository
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
        self, instance: Instance, *, subject: str, scopes: Sequence[str], name: str | None, via: str = "gateway"
    ) -> MintedToken: ...
    async def security_key(self, instance: Instance) -> str | None:
        """The ``OS_SECURITY_KEY`` of a security-key instance, decrypted."""
        ...


class InstancesFacadeImpl:
    def __init__(self, instances: InstanceRepository, tokens: TokenService, box: SecretBox) -> None:
        self._instances = instances
        self._tokens = tokens
        self._box = box

    async def get(self, ref: str) -> Instance | None:
        return await self._instances.get(ref)

    async def list(self) -> list[Instance]:
        return await self._instances.list()

    async def mint(
        self, instance: Instance, *, subject: str, scopes: Sequence[str], name: str | None, via: str = "gateway"
    ) -> MintedToken:
        return await self._tokens.mint(instance, subject=subject, scopes=scopes, name=name, via=via)

    async def security_key(self, instance: Instance) -> str | None:
        sealed = await self._instances.security_key(instance.id)
        return self._box.open(sealed).decode() if sealed else None
