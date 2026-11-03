"""Branch names and commit messages from the source's templates (``studio/{component}-v{version}``)."""

from __future__ import annotations

import re
import string
from collections.abc import Iterable, Mapping

from agnostic_sources.domain.model import SourceRuleError

DEFAULT_BRANCH_TEMPLATE = "studio/{component}-v{version}"
DEFAULT_COMMIT_TEMPLATE = "{component}: {summary}"
PLACEHOLDERS = frozenset({"component", "version", "kind", "instance", "author", "summary", "path", "count"})
MAX_SUBJECT = 72

_BAD_REF = re.compile(r"[\x00-\x20~^:?*\[\\\x7f]+")
_REPEATS = re.compile(r"/{2,}|\.{2,}")


def check_template(template: str, *, branch: bool) -> str:
    template = template.strip()
    if not template:
        raise SourceRuleError("A template can't be empty.")
    for _, name, _, _ in string.Formatter().parse(template):
        if name is not None and name not in PLACEHOLDERS:
            known = ", ".join(f"{{{item}}}" for item in sorted(PLACEHOLDERS))
            raise SourceRuleError(f"{{{name}}} isn't a placeholder; use {known}.")
    if branch:
        _ = branch_name(render(template, dict.fromkeys(PLACEHOLDERS, "x")))
    return template


def render(template: str, values: Mapping[str, object]) -> str:
    return string.Formatter().vformat(template, (), {key: str(values.get(key, "")) for key in PLACEHOLDERS})


def branch_name(raw: str) -> str:
    """``raw`` made a valid git branch name (git check-ref-format rules), or :class:`SourceRuleError`."""
    name = _BAD_REF.sub("-", raw.strip())
    name = _REPEATS.sub(lambda match: match.group(0)[0], name).replace("@{", "-")
    parts = [part.strip(".").removesuffix(".lock") for part in name.split("/")]
    name = "/".join(part for part in parts if part).strip("-/")
    if not name or name.startswith("-") or name == "@":
        raise SourceRuleError(f"{raw!r} can't be a branch name.")
    return name[:200]


def unique_branch(name: str, existing: Iterable[str]) -> str:
    taken = set(existing)
    if name not in taken:
        return name
    number = 2
    while f"{name}-{number}" in taken:
        number += 1
    return f"{name}-{number}"


def commit_message(template: str, values: Mapping[str, object], body: str | None = None) -> str:
    subject = render(template, values).strip().splitlines()[0] if render(template, values).strip() else "Studio"
    if len(subject) > MAX_SUBJECT:
        subject = subject[: MAX_SUBJECT - 1].rstrip() + "…"
    return f"{subject}\n\n{body.strip()}\n" if body and body.strip() else f"{subject}\n"
