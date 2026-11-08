"""Where artefacts are read from: a workspace directory, an E2B sandbox, or an Agno sandbox checkpoint.

Each source lists the regular files under one root and reads them back with a size cap. Paths are always relative
to that root, in POSIX form. A path that escapes the root (``..``, an absolute path, a symlink that points outside)
is refused, whatever a model or tool said about it.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import posixpath
import stat
import tarfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, runtime_checkable


class ArtifactSourceError(RuntimeError):
    """A source could not list or read a file (gone, too large, outside the root, sandbox unreachable)."""


@dataclass(frozen=True)
class SourceEntry:
    path: str
    """Relative to the source root, POSIX separators, never starting with ``/`` or containing ``..``."""
    size: int
    modified: float | None = None
    """Seconds since the epoch, when the source reports it."""


@runtime_checkable
class ArtifactSource(Protocol):
    """Lists and reads files a harness produced. Implement it to collect from another sandbox or agent server."""

    kind: str
    """Short name stored with every artefact (``directory``, ``e2b``, ``sandbox``)."""

    async def list(self) -> list[SourceEntry]: ...

    async def read(self, path: str, *, limit: int) -> bytes:
        """The file's bytes; raise :class:`ArtifactSourceError` when it is larger than ``limit``."""
        ...


def clean_relative(path: str) -> str:
    """``path`` as a relative POSIX path inside a root, or :class:`ArtifactSourceError`."""
    raw = path.replace("\\", "/").strip()
    if not raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise ArtifactSourceError(f"Not a relative path: {path!r}")
    normalized = posixpath.normpath(raw)
    if normalized in {".", ""} or normalized == ".." or normalized.startswith("../") or "\x00" in normalized:
        raise ArtifactSourceError(f"Path leaves the workspace: {path!r}")
    return normalized


def relative_to_root(path: str, root: str) -> str:
    """Accept a path as a tool reported it (absolute inside the root, or relative) and make it root-relative."""
    raw = path.replace("\\", "/").strip()
    base = root.replace("\\", "/").rstrip("/")
    if base and (raw == base or raw.startswith(f"{base}/")):
        raw = raw[len(base) :].lstrip("/")
    return clean_relative(raw)


class DirectorySource:
    """A directory on the runtime host: a ``ClaudeAgent``/``CodexAgent`` ``cwd``, or the folder Pi, OpenCode or any
    other harness writes to. Symlinks are not followed."""

    kind = "directory"

    def __init__(self, root: str | os.PathLike[str], *, max_entries: int = 5000) -> None:
        self.root = Path(root).resolve()
        self.max_entries = max_entries

    def _list(self) -> list[SourceEntry]:
        if not self.root.is_dir():
            return []
        entries: list[SourceEntry] = []
        for directory, folders, files in os.walk(self.root, followlinks=False):
            folders[:] = sorted(name for name in folders if not name.startswith(".") or name == ".agno")
            for name in sorted(files):
                full = Path(directory) / name
                try:
                    info = full.lstat()
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                entries.append(
                    SourceEntry(full.relative_to(self.root).as_posix(), info.st_size, modified=info.st_mtime)
                )
                if len(entries) >= self.max_entries:
                    return entries
        return entries

    def _resolve(self, path: str) -> Path:
        relative = clean_relative(path)
        full = self.root.joinpath(*PurePosixPath(relative).parts)
        # Any symlink on the way could lead elsewhere; resolve and compare instead of trusting the parts.
        if not full.resolve().is_relative_to(self.root):
            raise ArtifactSourceError(f"Path leaves the workspace: {path!r}")
        return full

    def _read(self, path: str, limit: int) -> bytes:
        full = self._resolve(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(full, flags)
        except OSError as error:
            raise ArtifactSourceError(f"Cannot open {path!r}: {error.strerror}") from error
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactSourceError(f"Not a regular file: {path!r}")
            if info.st_size > limit:
                raise ArtifactSourceError(f"{path!r} is larger than {limit} bytes")
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ArtifactSourceError(f"{path!r} is larger than {limit} bytes")
        return data

    async def list(self) -> list[SourceEntry]:
        return await asyncio.to_thread(self._list)

    async def read(self, path: str, *, limit: int) -> bytes:
        return await asyncio.to_thread(self._read, path, limit)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class E2BSource:
    """Files under ``root`` in an E2B sandbox, read through the E2B SDK (``files.list`` / ``files.read``).

    Pass the sandbox, the ``E2BTools`` that owns one, or a callable returning either; sync and async E2B clients both
    work. Collect before the sandbox is killed: an E2B sandbox's files are gone with it.
    """

    kind = "e2b"

    def __init__(self, sandbox: Any = None, *, tools: Any = None, root: str = "/home/user/outputs", depth: int = 8):
        if sandbox is None and tools is None:
            raise ValueError("E2BSource needs a sandbox or the E2BTools that owns one")
        self._sandbox = sandbox
        self._tools = tools
        self.root = root.rstrip("/") or "/"
        self.depth = depth

    def _client(self) -> Any:
        sandbox = self._sandbox() if callable(self._sandbox) and not hasattr(self._sandbox, "files") else self._sandbox
        if sandbox is None and self._tools is not None:
            sandbox = getattr(self._tools, "sandbox", None)
        if sandbox is None or not hasattr(sandbox, "files"):
            raise ArtifactSourceError("The E2B sandbox is not running")
        return sandbox

    async def _call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)
        return await _maybe_await(await asyncio.to_thread(function, *args, **kwargs))

    async def list(self) -> list[SourceEntry]:
        files = self._client().files
        try:
            items = await self._call(files.list, self.root, depth=self.depth)
        except Exception as error:  # the SDK raises its own NotFound/Timeout types
            if "not found" in str(error).lower():
                return []
            raise ArtifactSourceError(f"Cannot list {self.root} in the E2B sandbox: {error}") from error
        entries: list[SourceEntry] = []
        for item in items or []:
            kind = str(getattr(getattr(item, "type", None), "value", getattr(item, "type", ""))).lower()
            if kind not in {"file", "filetype.file"}:
                continue
            full = str(getattr(item, "path", "") or posixpath.join(self.root, str(getattr(item, "name", ""))))
            try:
                relative = relative_to_root(full, self.root)
            except ArtifactSourceError:
                continue
            modified = getattr(item, "modified_time", None)
            entries.append(
                SourceEntry(
                    relative,
                    int(getattr(item, "size", 0) or 0),
                    modified=modified.timestamp() if hasattr(modified, "timestamp") else None,
                )
            )
        return entries

    async def read(self, path: str, *, limit: int) -> bytes:
        full = posixpath.join(self.root, clean_relative(path))
        try:
            data = await self._call(self._client().files.read, full, format="bytes")
        except Exception as error:
            raise ArtifactSourceError(f"Cannot read {full} in the E2B sandbox: {error}") from error
        data = bytes(data)
        if len(data) > limit:
            raise ArtifactSourceError(f"{path!r} is larger than {limit} bytes")
        return data


def _member_name(name: str) -> str:
    return name[2:] if name.startswith("./") else name


class CheckpointSource:
    """Workspace files from an Agno sandbox checkpoint, the archive Agno stores after every sandboxed turn.

    Use it for ``ClaudeAgent(sandbox=DockerSandbox(...))`` and ``CodexAgent(sandbox=...)``: the computer may be paused
    or destroyed after the turn, but its workspace is in the checkpoint. ``archive`` returns an async context manager
    yielding the archive's path (``CheckpointStore.aopen_archive(reference)``); ``root`` is the folder inside the
    workspace to collect from.
    """

    kind = "sandbox"
    _WORKSPACE = "workspace"

    def __init__(self, archive: Callable[[], Any], *, root: str = "outputs") -> None:
        self._archive = archive
        self.root = clean_relative(root) if root not in {"", "."} else ""

    def _prefix(self) -> str:
        return f"{self._WORKSPACE}/{self.root}/" if self.root else f"{self._WORKSPACE}/"

    def _members(self, path: Path) -> list[tarfile.TarInfo]:
        with tarfile.open(path, "r:*") as archive:
            return [member for member in archive.getmembers() if member.isreg()]

    async def _with_archive(self, function: Callable[[Path], Any]) -> Any:
        context = await _maybe_await(self._archive())
        if context is None:
            return None
        async with context as path:
            return await asyncio.to_thread(function, Path(path))

    async def list(self) -> list[SourceEntry]:
        prefix = self._prefix()

        def entries(path: Path) -> list[SourceEntry]:
            found: list[SourceEntry] = []
            for member in self._members(path):
                name = _member_name(member.name)
                if not name.startswith(prefix):
                    continue
                try:
                    relative = clean_relative(name[len(prefix) :])
                except ArtifactSourceError:
                    continue
                found.append(SourceEntry(relative, member.size, modified=float(member.mtime)))
            return found

        return await self._with_archive(entries) or []

    async def read(self, path: str, *, limit: int) -> bytes:
        name = self._prefix() + clean_relative(path)

        def extract(archive_path: Path) -> bytes:
            with tarfile.open(archive_path, "r:*") as archive:
                for member in archive.getmembers():
                    if member.isreg() and _member_name(member.name) == name:
                        if member.size > limit:
                            raise ArtifactSourceError(f"{path!r} is larger than {limit} bytes")
                        stream = archive.extractfile(member)
                        if stream is None:
                            break
                        return stream.read(limit + 1)
            raise ArtifactSourceError(f"{path!r} is not in the checkpoint")

        data = await self._with_archive(extract)
        if data is None:
            raise ArtifactSourceError("The session has no sandbox checkpoint yet")
        return data


SourceFactory = Callable[[Any], "ArtifactSource | Awaitable[ArtifactSource | None] | None"]
"""Builds the source for one run from its context (``RunContext`` / session), for sources tied to a session."""
