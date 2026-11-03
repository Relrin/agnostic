"""``python -m agnostic_codegen DIR``: write the generated code next to every ``agents/*.json`` and ``teams/*.json``.

Used for the golden fixtures: the JSON comes from agno's ``to_dict()`` in the reference runtime, the ``.py`` next to it
is what Studio shows for that config.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agnostic_codegen import render
from agnostic_spec.v3_1 import parse


def write_all(folder: Path) -> int:
    written = 0
    for path in sorted(folder.glob("*/*.json")):
        kind = "team" if path.parent.name == "teams" else "agent"
        config = parse(kind, json.loads(path.read_text(encoding="utf-8")))
        rendered = asyncio.run(render(config))
        if not rendered.ruff.available:
            raise SystemExit(f"ruff couldn't run: {rendered.ruff.error}")
        path.with_suffix(".py").write_text(rendered.code, encoding="utf-8", newline="\n")
        written += 1
    return written


def main() -> None:
    if len(sys.argv) != 2:  # noqa: PLR2004
        raise SystemExit("usage: python -m agnostic_codegen <golden folder>")
    print(f"wrote {write_all(Path(sys.argv[1]))} files")  # noqa: T201


if __name__ == "__main__":
    main()
