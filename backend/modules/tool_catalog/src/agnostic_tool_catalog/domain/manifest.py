"""What a runtime's bridge pulls: the active entries for its instance, with a revision per entry and an ETag.

The manifest holds no secret: credentials stay environment variable names the bridge resolves on the runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from agnostic_tool_catalog.domain.entries import Entry

MANIFEST_VERSION = 1


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def manifest_entry(entry: Entry) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": entry.registry_name,
        "kind": entry.kind,
        "display_name": entry.display_name,
        "local": entry.local,
        "requires_confirmation_tools": list(entry.requires_confirmation_tools),
    }
    if entry.kind == "mcp":
        item |= dict(entry.config)
    else:
        item |= {"toolkit": entry.toolkit_key, "params": dict(entry.config.get("params") or {})}
    return item | {"revision": _digest(item)[:16]}


def build_manifest(instance_id: str, entries: Iterable[Entry]) -> dict[str, Any]:
    items = sorted(
        (manifest_entry(entry) for entry in entries if entry.status == "active" and entry.applies_to(instance_id)),
        key=lambda item: str(item["name"]),
    )
    return {"version": MANIFEST_VERSION, "instance_id": instance_id, "entries": items}


def etag(manifest: dict[str, Any]) -> str:
    return f'"{_digest(manifest)[:32]}"'
