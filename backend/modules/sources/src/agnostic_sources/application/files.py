"""A source's files, whether it is a git mirror or a local folder: fetch, list, read, last commit, remote."""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_sources.application.ports import (
    Folders,
    GitRepo,
    ProviderClient,
    ProviderClients,
    ProviderError,
    Remote,
    SourceLimits,
    SourceStore,
)
from agnostic_sources.domain.model import CommitInfo, Connection, Source
from agnostic_sources.domain.paths import component_target, folder_digest
from agnostic_sources.domain.remote import check_clone_url


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The files of a source at one point: ``head`` is a commit sha (or a digest of a local folder)."""

    head: str
    files: dict[str, str]
    """Path → blob id (git) or content hash (folder)."""


class SourceFiles:
    def __init__(
        self,
        store: SourceStore,
        git: GitRepo,
        clients: ProviderClients,
        folders: Folders,
        settings: SourceLimits,
    ) -> None:
        self._store = store
        self._git = git
        self._clients = clients
        self._folders = folders
        self._settings = settings

    @property
    def git(self) -> GitRepo:
        return self._git

    @property
    def folders(self) -> Folders:
        return self._folders

    async def connection(self, source: Source) -> Connection | None:
        """The source's connection (``None`` for local folders and public clone URLs)."""
        if source.connection_id is None:
            return None
        connection = await self._store.connection(source.connection_id)
        if connection is None:
            raise NotFoundError("The source's connection was removed.")
        return connection

    async def client(self, source: Source) -> ProviderClient | None:
        connection = await self.connection(source)
        if connection is None:
            return None
        return self._clients.client(connection, await self._store.connection_secrets(connection.id))

    async def local_hash(self, source: Source, path: str) -> str | None:
        """The hash of a local folder's file as it is on disk now, as a fetch lists it (``None`` when it is gone)."""
        return self._folders.digest(source.local_path or "", path)

    async def remote(self, source: Source) -> Remote:
        client = await self.client(source)
        if client is None:
            if not source.clone_url:
                raise ProviderError("The source has neither a connection nor a clone URL.")
            return Remote(check_clone_url(source.clone_url, allow_file=self._settings.allow_file_remotes))
        if source.clone_url:
            _ = check_clone_url(source.clone_url, allow_file=self._settings.allow_file_remotes)
        return await client.remote(source.repo, source.clone_url)

    async def fetch(self, source: Source) -> Snapshot:
        """Bring the source up to date and list its files."""
        if source.is_local:
            files = self._folders.files(source.local_path or "")
            return Snapshot(folder_digest(files), files)
        result = await self._git.fetch(source.id, await self.remote(source), source.branch)
        return Snapshot(result.head, await self._git.files(source.id, result.head))

    async def snapshot(self, source: Source) -> Snapshot | None:
        """The files as of the last fetch (``None`` before the first)."""
        if source.head_sha is None:
            return None
        if source.is_local:
            return await self.fetch(source)
        return Snapshot(source.head_sha, await self._git.files(source.id, source.head_sha))

    async def read(self, source: Source, head: str, path: str) -> str | None:
        if source.is_local:
            data = self._folders.read(source.local_path or "", path)
        else:
            data = await self._git.read(source.id, await self.remote(source), head, path)
        if data is None or len(data) > self._settings.max_file_bytes:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def last_commit(self, source: Source, head: str, path: str) -> CommitInfo | None:
        if source.is_local:
            return CommitInfo(head, "Local folder", "", utcnow(), f"Changed on disk: {path}")
        return await self._git.last_commit(source.id, head, path)


def mapped_files(source: Source, files: dict[str, str]) -> dict[str, str]:
    """The files that hold agents, teams or workflows."""
    return {path: blob for path, blob in files.items() if component_target(source.mappings, path) is not None}
