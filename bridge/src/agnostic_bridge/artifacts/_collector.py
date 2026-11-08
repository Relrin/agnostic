"""Reconcile a source with what a session already has: new and changed files become artefacts.

The collector is the source of truth for what a harness produced. Tool events (a ``write_file`` call, Claude's
``Write``) only say a file was probably written; Bash and scripts write without any event. So at the end of a run the
collector lists the source, reads every matching file, hashes it, and attaches the ones whose hash it has not seen in
this session. The seen hashes live in the session state (``agnostic_artifacts``), so a file is attached once per
version, on the run that produced that version.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, MutableMapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from agno.utils.log import log_warning

from agnostic_bridge.artifacts._media import build_media
from agnostic_bridge.artifacts._sources import ArtifactSource, ArtifactSourceError, SourceEntry

STATE_KEY = "agnostic_artifacts"
DEFAULT_EXCLUDE = (
    ".agno/**",
    "**/.git/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/*.pyc",
    "**/.DS_Store",
)
MiB = 1024 * 1024


@cache
def _pattern(glob: str) -> re.Pattern[str]:
    """``**`` spans folders, ``*`` and ``?`` stay inside one; a leading ``**/`` also matches at the root."""
    out, index = [], 0
    while index < len(glob):
        if glob.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, globs: Iterable[str]) -> bool:
    return any(_pattern(glob).match(path) for glob in globs)


@dataclass
class ArtifactCollector:
    """Collect files from ``source`` that match ``include`` and not ``exclude``.

    Limits keep a runaway harness from filling the media storage: at most ``max_files`` files and ``max_total_bytes``
    per run, each at most ``max_file_bytes``. Files over a limit are skipped and logged, never truncated.
    """

    source: ArtifactSource
    include: Sequence[str] = ("**",)
    exclude: Sequence[str] = DEFAULT_EXCLUDE
    max_file_bytes: int = 25 * MiB
    max_files: int = 50
    max_total_bytes: int = 100 * MiB
    producer: str | None = None
    _key: str = field(init=False)

    def __post_init__(self) -> None:
        root = getattr(self.source, "root", "")
        self._key = f"{self.source.kind}:{root}"

    def wanted(self, entry: SourceEntry) -> bool:
        return matches(entry.path, self.include) and not matches(entry.path, self.exclude)

    def seen(self, state: MutableMapping[str, Any] | None) -> dict[str, dict[str, Any]]:
        if state is None:
            return {}
        bucket = state.setdefault(STATE_KEY, {})
        return bucket.setdefault(self._key, {}) if isinstance(bucket, dict) else {}

    async def collect(
        self, state: MutableMapping[str, Any] | None = None, *, paths: Sequence[str] | None = None
    ) -> list[Any]:
        """New or changed files as Agno media. ``state`` is the session state the seen hashes are kept in;
        ``paths`` limits the pass to those files (a publish), otherwise the whole source is reconciled."""
        try:
            entries = await self.source.list()
        except ArtifactSourceError as error:
            log_warning(f"Artifacts: cannot list {self._key}: {error}")
            return []
        if paths is not None:
            wanted = set(paths)
            entries = [entry for entry in entries if entry.path in wanted]
        else:
            entries = [entry for entry in entries if self.wanted(entry)]
        seen = self.seen(state)
        media: list[Any] = []
        total = 0
        for entry in sorted(entries, key=lambda item: item.path):
            if len(media) >= self.max_files:
                log_warning(f"Artifacts: over {self.max_files} files in {self._key}; the rest wait for the next run")
                break
            if entry.size > self.max_file_bytes or total + entry.size > self.max_total_bytes:
                log_warning(f"Artifacts: skipped {entry.path} ({entry.size} bytes) over the size limit")
                continue
            previous = seen.get(entry.path)
            if previous and entry.modified is not None and previous.get("modified") == entry.modified:
                continue  # unchanged since the last pass; skip the read
            try:
                data = await self.source.read(entry.path, limit=self.max_file_bytes)
            except ArtifactSourceError as error:
                log_warning(f"Artifacts: cannot read {entry.path}: {error}")
                continue
            digest = hashlib.sha256(data).hexdigest()
            if previous and previous.get("sha256") == digest:
                previous["modified"] = entry.modified
                continue
            revision = int(previous.get("revision", 0)) + 1 if previous else 1
            media.append(
                build_media(entry.path, data, source=self.source.kind, producer=self.producer, revision=revision)
            )
            seen[entry.path] = {"sha256": digest, "modified": entry.modified, "revision": revision}
            total += len(data)
        return media
