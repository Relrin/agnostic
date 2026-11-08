"""Artefacts read straight from a live sandbox's workspace, through the provider's command channel.

The folder is archived with ``tar`` inside the sandbox and parsed here, so nothing in the sandbox is trusted to
report its own paths: members that are not regular files, or whose names leave the folder, are ignored.
"""

from __future__ import annotations

import base64
import io
import tarfile
from typing import TYPE_CHECKING

from agnostic_bridge.artifacts._sources import ArtifactSourceError, SourceEntry, clean_relative

if TYPE_CHECKING:
    from agnostic_bridge.coding._providers import SandboxLease, SandboxProvider

MAX_ARCHIVE_BYTES = 2_500_000
# The command channel returns at most 4 MiB of text and a provider may stop a sandbox whose command overflows it,
# so the archive is built inside the sandbox within a budget and travels base64-encoded. Files past the budget are
# left for a later turn rather than truncated.
_ARCHIVE = """
import base64, io, os, sys, tarfile
workspace, root, budget = sys.argv[1], sys.argv[2], int(sys.argv[3])
buffer, used = io.BytesIO(), 0
with tarfile.open(fileobj=buffer, mode="w") as archive:
    base = os.path.join(workspace, root)
    for folder, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(folder, d)))
        for name in sorted(files):
            path = os.path.join(folder, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            if used + size > budget:
                continue
            used += size
            archive.add(path, arcname=os.path.relpath(path, workspace), recursive=False)
sys.stdout.write(base64.b64encode(buffer.getvalue()).decode())
"""


class SandboxWorkspaceSource:
    """Regular files under ``root`` of the sandbox workspace, with paths relative to the workspace."""

    kind = "docker"

    def __init__(self, provider: SandboxProvider, lease: SandboxLease, *, root: str = "outputs") -> None:
        self._provider = provider
        self._lease = lease
        self.root = clean_relative(root)
        self.kind = provider.kind
        self._cache: dict[str, tuple[int, bytes]] | None = None

    async def _members(self) -> dict[str, tuple[int, bytes]]:
        if self._cache is not None:
            return self._cache
        result = await self._provider.exec(
            self._lease,
            ["python3", "-I", "-c", _ARCHIVE, self._lease.workspace, self.root, str(MAX_ARCHIVE_BYTES)],
            timeout=60,
        )
        if result.exit_code != 0 or not result.stdout.strip():
            self._cache = {}
            return self._cache
        try:
            raw = base64.b64decode(result.stdout.strip(), validate=False)
        except ValueError as error:
            raise ArtifactSourceError("The sandbox returned an unreadable archive") from error
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ArtifactSourceError("The sandbox workspace archive is too large")
        members: dict[str, tuple[int, bytes]] = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive.getmembers():
                if not member.isreg():
                    continue
                name = member.name[2:] if member.name.startswith("./") else member.name
                try:
                    relative = clean_relative(name)
                except ArtifactSourceError:
                    continue
                if not (relative == self.root or relative.startswith(self.root + "/")):
                    continue
                stream = archive.extractfile(member)
                members[relative] = (int(member.mtime), stream.read() if stream is not None else b"")
        self._cache = members
        return members

    async def list(self) -> list[SourceEntry]:
        return [
            SourceEntry(path, len(data), modified=float(mtime))
            for path, (mtime, data) in (await self._members()).items()
        ]

    async def read(self, path: str, *, limit: int) -> bytes:
        found = (await self._members()).get(clean_relative(path))
        if found is None:
            raise ArtifactSourceError(f"{path!r} is not in the sandbox workspace")
        if len(found[1]) > limit:
            raise ArtifactSourceError(f"{path!r} is larger than {limit} bytes")
        return found[1]
