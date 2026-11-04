"""Turning what someone typed into the palette into search terms. No I/O."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[0-9A-Za-zÀ-￿]+")
MAX_TERMS = 8


def terms(text: str) -> list[str]:
    """Lower-cased word fragments: ``"Support-triage v3"`` → ``["support", "triage", "v3"]``."""
    return [token.lower() for token in _TOKEN.findall(text)][:MAX_TERMS]


def prefix_tsquery(text: str) -> str | None:
    """A ``to_tsquery('simple', …)`` expression where every term is a prefix: ``support:* & tri:*``."""
    found = terms(text)
    return " & ".join(f"{term}:*" for term in found) if found else None


def like_pattern(text: str) -> str:
    r"""``%text%`` with LIKE wildcards in the input escaped (``\`` is the escape character)."""
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"
