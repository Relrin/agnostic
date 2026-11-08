"""Read an artefact's bytes from its instance, as the person asking, and decide how to serve them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import quote

from agnostic_artifacts.domain.content import Disposition, ServedContent, serve
from agnostic_gateway.facade import BinaryResponse, GatewayFacade
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError, ServiceUnavailableError

MiB = 1024 * 1024
NOT_FOUND = 404
FORBIDDEN = 403
UNAVAILABLE = 503
NOT_IMPLEMENTED = 501


class ArtifactFetchError(AppError):
    status = 502
    code = "artifact_unavailable"
    title = "The instance could not return the artefact"


def media_path(session_id: str, storage_key: str) -> str:
    """AgentOS's media route for one stored object; the key keeps its folders."""
    return f"/sessions/{quote(session_id, safe='')}/media/{quote(storage_key, safe='/')}"


def checked(instance: Instance, status: int, body: bytes) -> bytes:
    if 200 <= status < 300:  # noqa: PLR2004
        return body
    if status == NOT_FOUND:
        raise NotFoundError(f"{instance.display_name} has no such artefact in this session")
    if status == FORBIDDEN:
        raise ForbiddenError(f"{instance.display_name} refused access to this artefact")
    if status in {UNAVAILABLE, NOT_IMPLEMENTED}:
        raise ServiceUnavailableError(
            f"{instance.display_name} has no media storage configured, so it keeps no artefacts to serve"
        )
    raise ArtifactFetchError(f"{instance.display_name} answered HTTP {status}", extra={"upstream_status": status})


@dataclass(frozen=True, slots=True)
class Fetched:
    data: bytes
    declared: str | None
    sha256: str

    def served(self, filename: str, disposition: Disposition) -> ServedContent:
        return serve(filename, self.data, declared=self.declared, disposition=disposition)


class ArtifactContent:
    def __init__(self, gateway: GatewayFacade, max_content_mb: int) -> None:
        self._gateway = gateway
        self._max_bytes = max_content_mb * MiB

    async def instance(self, ref: str) -> Instance:
        return await self._gateway.instance(ref)

    async def fetch(self, principal: Principal, instance: Instance, session_id: str, storage_key: str) -> Fetched:
        response: BinaryResponse = await self._gateway.fetch(
            principal, instance, media_path(session_id, storage_key), max_bytes=self._max_bytes
        )
        data = checked(instance, response.status, response.body)
        return Fetched(data, response.headers.get("content-type"), hashlib.sha256(data).hexdigest())
