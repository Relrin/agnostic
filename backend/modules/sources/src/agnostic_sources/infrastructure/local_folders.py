"""Local folder sources: a folder mounted into Agnostic and the instance, read and written in place."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from agnostic_sources.domain.model import SourceRuleError
from agnostic_sources.domain.paths import MAX_FOLDER_FILES, check_path
from agnostic_sources.settings import SourcesSettings

SKIPPED = frozenset({".git", ".hg", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"})


class LocalFolders:
    def __init__(self, settings: SourcesSettings) -> None:
        self._roots = [root.resolve() for root in settings.local_roots]
        self._max_bytes = settings.max_file_bytes

    def allowed_roots(self) -> list[str]:
        return [str(root) for root in self._roots]

    def check_root(self, root: str) -> str:
        if not self._roots:
            raise SourceRuleError("Local folders are turned off here (set AGNOSTIC_SOURCES__LOCAL_ROOTS).")
        resolved = Path(root).resolve()
        if not any(resolved == allowed or resolved.is_relative_to(allowed) for allowed in self._roots):
            allowed = ", ".join(str(item) for item in self._roots)
            raise SourceRuleError(f"{root} isn't inside a folder local sources may use ({allowed}).")
        if not resolved.is_dir():
            raise SourceRuleError(f"{root} isn't a folder Agnostic can see.")
        return str(resolved)

    def _file(self, root: str, path: str) -> Path:
        base = Path(self.check_root(root))
        target = (base / check_path(path)).resolve()
        if not target.is_relative_to(base):
            raise SourceRuleError(f"{path} leads outside the folder.")
        return target

    def files(self, root: str) -> dict[str, str]:
        base = Path(self.check_root(root))
        found: dict[str, str] = {}
        for folder, directories, names in os.walk(base, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in SKIPPED and not name.startswith("."))
            for name in sorted(names):
                full = Path(folder) / name
                if full.is_symlink() or not full.is_file():
                    continue
                # Files too large to read are listed too: their hash is what a write-back compares against.
                found[full.relative_to(base).as_posix()] = _digest(full)
                if len(found) >= MAX_FOLDER_FILES:
                    return found
        return found

    def digest(self, root: str, path: str) -> str | None:
        target = self._file(root, path)
        if target.is_symlink() or not target.is_file():
            return None
        return _digest(target)

    def read(self, root: str, path: str) -> bytes | None:
        target = self._file(root, path)
        if target.is_symlink() or not target.is_file() or target.stat().st_size > self._max_bytes:
            return None
        return target.read_bytes()

    def write(self, root: str, path: str, data: bytes) -> None:
        target = self._file(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".agnostic-", dir=target.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                _ = stream.write(data)
            _ = Path(temporary).replace(target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def _digest(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
