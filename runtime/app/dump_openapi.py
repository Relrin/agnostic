"""Write the runtime's OpenAPI document (sorted, stable) for the agnostic-agentos-client model generator.

    uv run python -m app.dump_openapi ../backend/packages/agnostic-agentos-client/openapi/agentos-3.1.12.json

agno logs to stdout, so the document goes to a file rather than being printed.
"""

import json
import sys
from pathlib import Path

from app.main import app

if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
