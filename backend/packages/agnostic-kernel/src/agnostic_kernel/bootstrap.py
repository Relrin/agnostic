"""``agnostic bootstrap``: the first org and Owner. The ``org`` module provides the implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OwnerAccount:
    email: str
    display_name: str
    password: str


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    org_name: str
    owner_email: str | None
    """Set when the Owner account was created directly."""
    setup_url: str | None
    """One-time first-run link, when the Owner signs up in the browser instead."""


class Bootstrapper(Protocol):
    async def bootstrap(self, org_name: str, owner: OwnerAccount | None) -> BootstrapResult: ...
