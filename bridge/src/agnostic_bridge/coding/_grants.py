"""Per-run credentials a sandbox uses to call back into the runtime for its model and tools.

A grant is minted when a turn starts and revoked when it ends. The token is random, the store keeps only its hash,
and the grant is bound to one agent, session and run: it reaches that agent's model and that agent's tools and
nothing else. Provider keys stay in this process.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.tools.function import Function


class GrantExhausted(Exception):
    """The run made more model requests than its grant allows."""


@dataclass
class RunGrant:
    agent_id: str
    session_id: str
    run_id: str
    model: Model
    functions: dict[str, Function]
    expires_at: float
    max_requests: int = 200
    requests: int = 0
    usage: MessageMetrics = field(default_factory=MessageMetrics)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at

    def count_request(self) -> None:
        with self._lock:
            if self.requests >= self.max_requests:
                raise GrantExhausted(f"Run {self.run_id} used its {self.max_requests} model requests")
            self.requests += 1

    def add_usage(self, metrics: MessageMetrics | None) -> None:
        if metrics is None:
            return
        with self._lock:
            self.usage += metrics


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class GrantStore:
    """In-memory grants of this process; each replica serves only the sandboxes its own turns started."""

    def __init__(self) -> None:
        self._grants: dict[bytes, RunGrant] = {}
        self._lock = threading.Lock()

    def mint(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        model: Model,
        functions: dict[str, Function] | None = None,
        ttl: float,
        **limits: Any,
    ) -> tuple[str, RunGrant]:
        token = "agr_" + secrets.token_urlsafe(32)
        grant = RunGrant(
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            model=model,
            functions=dict(functions or {}),
            expires_at=time.monotonic() + ttl,
            **limits,
        )
        with self._lock:
            self._sweep()
            self._grants[_digest(token)] = grant
        return token, grant

    def verify(self, token: str | None) -> RunGrant | None:
        if not token or not token.startswith("agr_") or len(token) > 128:
            return None
        digest = _digest(token)
        with self._lock:
            # Every known digest is compared in constant time, so timing says nothing about near misses.
            for known, grant in self._grants.items():
                if hmac.compare_digest(known, digest):
                    return None if grant.expired else grant
        return None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._grants.pop(_digest(token), None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._grants)

    def _sweep(self) -> None:
        for key in [key for key, grant in self._grants.items() if grant.expired]:
            del self._grants[key]
