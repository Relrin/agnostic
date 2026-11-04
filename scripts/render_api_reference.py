"""Render docs/reference/api.md from the OpenAPI document (``frontend/packages/api/openapi.json``).

    python scripts/render_api_reference.py            # rewrite docs/reference/api.md
    python scripts/render_api_reference.py --check    # exit 1 when the committed page is stale (CI)

The page lists every operation by tag with its summary; the OpenAPI document itself (``/api/v1/openapi.json``) and
the interactive docs (``/api/v1/docs``) stay the precise reference.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "frontend" / "packages" / "api" / "openapi.json"
PAGE = ROOT / "docs" / "reference" / "api.md"
METHODS = ("get", "post", "put", "patch", "delete")

HEADER = """# API reference

Generated from the OpenAPI document by `scripts/render_api_reference.py`; don't edit by hand. Every route is under
the API's origin; `/api/v1` is stable from 1.0 (breaking changes need `/api/v2`). Conventions (problem details,
request ids, cursor pagination, CSRF on cookie sessions, bearer service-account tokens):
[API conventions](api-conventions.md). The full schema: `GET /api/v1/openapi.json`; interactive: `/api/v1/docs`.

AgentOS routes are called through the gateway, `ANY /api/v1/instances/{instance}/os/{path}`, as the signed-in person;
they're described by the runtime's own OpenAPI document and not repeated here.
"""


def render(spec: dict[str, Any]) -> str:
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for path, item in sorted(spec.get("paths", {}).items()):
        for method in METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            tag = (operation.get("tags") or ["other"])[0]
            summary = str(operation.get("summary") or operation.get("operationId") or "").replace("|", "\\|")
            groups.setdefault(tag, []).append((method.upper(), path, summary))
    lines = [HEADER.rstrip(), ""]
    for tag in sorted(groups):
        lines += [f"## {tag}", "", "| Method | Path | Does |", "|---|---|---|"]
        lines += [f"| `{method}` | `{path}` | {summary} |" for method, path, summary in groups[tag]]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when docs/reference/api.md is stale")
    args = parser.parse_args()
    page = render(json.loads(SPEC.read_text(encoding="utf-8")))
    if args.check:
        current = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
        if current != page:
            print("docs/reference/api.md is stale: run `just api-gen`", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
