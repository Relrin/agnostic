"""Path mappings: which repository files are agents, teams, workflows, the registry, or nothing to Studio.

Globs follow gitignore-like rules: ``*`` stays inside one folder, ``**`` crosses folders, a trailing ``/`` means
everything under that folder, and ``a, b`` lists several patterns. Paths are POSIX, relative to the repository root.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

from agnostic_sources.domain.model import PathMapping, SourceRuleError, TargetKind

DEFAULT_MAPPINGS: tuple[PathMapping, ...] = (
    PathMapping("agents/*.py", "agents"),
    PathMapping("teams/*.py", "teams"),
    PathMapping("workflows/*.py", "workflows"),
    PathMapping("registry.py", "registry", writable=False),
    PathMapping("tests/, utils/", "ignored", writable=False),
)
TARGET_KINDS: frozenset[str] = frozenset({"agents", "teams", "workflows", "registry", "ignored"})
MAX_MAPPINGS = 50
_GLOB_CHARS = re.compile(r"[*?\[]")


def patterns(glob: str) -> list[str]:
    """``"tests/, utils/"`` → ``["tests/", "utils/"]``."""
    return [part.strip() for part in glob.split(",") if part.strip()]


def check_path(path: str) -> str:
    """A safe repository-relative POSIX path, or :class:`SourceRuleError`."""
    if not path or "\\" in path or path.startswith("/") or "\x00" in path or re.match(r"^[A-Za-z]:", path):
        raise SourceRuleError(f"{path!r} isn't a path inside the repository.")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts[:-1]) or parts[-1] in {"", ".", ".."}:
        raise SourceRuleError(f"{path!r} isn't a path inside the repository.")
    return path


def check_mappings(mappings: Sequence[PathMapping]) -> tuple[PathMapping, ...]:
    if len(mappings) > MAX_MAPPINGS:
        raise SourceRuleError(f"Keep to {MAX_MAPPINGS} path mappings.")
    for mapping in mappings:
        if mapping.target_kind not in TARGET_KINDS:
            raise SourceRuleError(f"{mapping.target_kind!r} isn't something a path can map to.")
        found = patterns(mapping.glob)
        if not found:
            raise SourceRuleError("A path mapping needs a pattern.")
        for pattern in found:
            _ = check_path(pattern.rstrip("/") or ".")
            _ = compile_glob(pattern)
    return tuple(mappings)


@lru_cache(maxsize=512)
def compile_glob(pattern: str) -> re.Pattern[str]:
    if pattern.endswith("/"):
        return re.compile(re.escape(pattern) + ".*")
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                raise SourceRuleError(f"{pattern!r} has an unclosed [.")
            body = pattern[index + 1 : end].replace("\\", "\\\\")
            out.append(f"[{'^' + body[1:] if body.startswith('!') else body}]")
            index = end
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out))


def matches(glob: str, path: str) -> bool:
    return any(compile_glob(pattern).fullmatch(path) for pattern in patterns(glob))


def match(mappings: Iterable[PathMapping], path: str) -> PathMapping | None:
    """The mapping ``path`` falls under: an ``ignored`` mapping always wins, otherwise the first that matches."""
    found: PathMapping | None = None
    for mapping in mappings:
        if not matches(mapping.glob, path):
            continue
        if mapping.target_kind == "ignored":
            return mapping
        found = found or mapping
    return found


def component_target(mappings: Iterable[PathMapping], path: str) -> PathMapping | None:
    """The mapping when ``path`` holds agents, teams or workflows; ``None`` for the registry, ignored and unmapped."""
    found = match(mappings, path)
    return found if found is not None and found.target_kind in {"agents", "teams", "workflows"} else None


def pathspecs(mappings: Iterable[PathMapping]) -> list[str]:
    """Git pathspecs for every mapped (not ignored) pattern, so git itself scopes diffs to them."""
    specs: list[str] = []
    for mapping in mappings:
        if mapping.target_kind == "ignored":
            continue
        for pattern in patterns(mapping.glob):
            spec = f":(glob){pattern}**" if pattern.endswith("/") else f":(glob){pattern}"
            if spec not in specs:
                specs.append(spec)
    return specs


def folder_of(glob: str) -> str:
    """Where new files for a mapping go: the pattern's fixed folder (``agents/*.py`` → ``agents``)."""
    first = patterns(glob)[0] if patterns(glob) else ""
    folder: list[str] = []
    for part in first.split("/")[:-1]:
        if _GLOB_CHARS.search(part):
            break
        folder.append(part)
    return "/".join(folder)


def counts(mappings: Sequence[PathMapping], paths: Iterable[str]) -> list[int]:
    """How many of ``paths`` each mapping takes (the "Agents · 6" counts), in mapping order."""
    totals = [0] * len(mappings)
    for path in paths:
        found = match(mappings, path)
        if found is None:
            continue
        totals[mappings.index(found)] += 1
    return totals


def target_for_kind(kind: str) -> TargetKind:
    return {"agent": "agents", "team": "teams", "workflow": "workflows"}[kind]  # pyright: ignore[reportReturnType]


def folder_digest(files: dict[str, str]) -> str:
    """One hash for a local folder's state (path → content hash): what stands in for a commit sha."""
    joined = "\n".join(f"{path}:{value}" for path, value in sorted(files.items()))
    return hashlib.sha256(joined.encode()).hexdigest()[:40]
