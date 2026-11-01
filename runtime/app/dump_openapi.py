"""Write the runtime's OpenAPI document (sorted, stable) for the agnostic-agentos-client model generator.

    uv run python -m app.dump_openapi ../backend/packages/agnostic-agentos-client/openapi/agentos-3.1.12.json

The document describes AgentOS itself, so the agnostic-bridge routes (``/agnostic/…``) and the schemas only they use
are left out. agno logs to stdout, so the document goes to a file rather than being printed.
"""

import json
import sys
from pathlib import Path
from typing import Any

from agnostic_bridge import BRIDGE_PREFIX

from app.main import app

_REF_PREFIX = "#/components/schemas/"


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            found.add(ref.removeprefix(_REF_PREFIX))
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def _reachable(paths: dict[str, Any], schemas: dict[str, Any]) -> set[str]:
    seen: set[str] = set()
    pending = _refs(paths)
    while pending:
        name = pending.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        pending |= _refs(schemas[name])
    return seen


def agentos_openapi(document: dict[str, Any]) -> dict[str, Any]:
    """``document`` without the bridge's paths and the component schemas nothing else references."""
    bridge_root = BRIDGE_PREFIX.rsplit("/", 1)[0] + "/"  # "/agnostic/"
    all_paths = document.get("paths", {})
    paths = {path: item for path, item in all_paths.items() if not path.startswith(bridge_root)}
    schemas = document.get("components", {}).get("schemas", {})
    dropped = _reachable(all_paths, schemas) - _reachable(paths, schemas)
    result = {**document, "paths": paths}
    if dropped:
        components = {**result["components"], "schemas": {k: v for k, v in schemas.items() if k not in dropped}}
        result["components"] = components
    return result


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    document = agentos_openapi(app.openapi())
    target.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
