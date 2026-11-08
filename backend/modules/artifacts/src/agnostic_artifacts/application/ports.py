"""Ports of the artefacts module, and its scopes."""

from __future__ import annotations

from typing import Protocol

from agnostic_artifacts.domain.shares import Share

SHARE = "artifacts:share"
"""Create share links for artefacts you can read, and revoke your own."""
MANAGE = "artifacts:manage"
"""See and revoke everyone's share links."""


class ShareRepository(Protocol):
    async def add(self, share: Share, token_hash: str) -> None: ...
    async def get(self, share_id: str) -> Share | None: ...
    async def by_token(self, token_hash: str) -> Share | None: ...
    async def list(
        self, instance_id: str, *, session_id: str | None = None, created_by: str | None = None
    ) -> list[Share]: ...
    async def save(self, share: Share) -> None: ...
    async def commit(self) -> None: ...
