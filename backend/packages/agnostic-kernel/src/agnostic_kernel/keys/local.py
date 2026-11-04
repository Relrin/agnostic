"""The master key itself, base64, in the configuration (a file mounted from a secret store, or an env var)."""

from __future__ import annotations

from collections.abc import Mapping

from agnostic_kernel.crypto import decode_local_key, encode_local_key


class LocalKeyProvider:
    name = "local"

    async def wrap(self, key: bytes) -> str:
        return encode_local_key(key)

    async def unwrap(self, wrapped: str) -> bytes:
        return decode_local_key(wrapped)

    def describe(self) -> Mapping[str, str]:
        return {"provider": self.name}

    async def aclose(self) -> None:
        return None
