"""License policy check of a built image, from its CycloneDX SBOM (``syft agnostic:dev -o cyclonedx-json``).

The lockfile checks (``check_python_licenses.py``, ``frontend/scripts/check-licenses.mjs``) cover what we install;
this one covers what actually ends up in the image, operating-system packages of the base image included. The same
policy applies to Python and npm components; Debian packages of the base image are reported, and fail only on
licenses that are forbidden for anything we ship.

    python scripts/check_sbom_licenses.py sbom.cdx.json

Exit code 1 on a forbidden license, or on a Python/npm component that is unknown or unreviewed weak copyleft.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_python_licenses import FORBIDDEN, OVERRIDES, PERMISSIVE, WEAK_ALLOWED, WEAK_COPYLEFT  # noqa: E402

# Weak-copyleft npm packages reviewed for the web build (mirrors frontend/scripts/check-licenses.mjs).
WEB_WEAK_ALLOWED = {"elkjs"}
OWN = re.compile(r"^(agnostic|@agnostic/)")
# Base-image system packages: GPL/LGPL tools of the distribution are fine as separate programs; only licenses we
# never accept in an artifact fail.
SYSTEM_FORBIDDEN = re.compile(r"\b(SSPL|Server Side Public|BUSL|Business Source|Commons Clause|RSAL)\b", re.IGNORECASE)


def licenses_of(component: dict[str, Any]) -> str:
    names: list[str] = []
    for entry in component.get("licenses", []):
        if "expression" in entry:
            names.append(str(entry["expression"]))
        license_info = entry.get("license", {})
        names.extend(str(license_info[key]) for key in ("id", "name") if license_info.get(key))
    return " OR ".join(names) or "UNKNOWN"


def ecosystem(component: dict[str, Any]) -> str:
    purl = str(component.get("purl", ""))
    for kind in ("pypi", "npm", "deb", "apk", "rpm", "golang"):
        if purl.startswith(f"pkg:{kind}/"):
            return kind
    return "other"


def verdict(name: str, kind: str, text: str) -> str:
    lowered = name.lower()
    if kind in {"deb", "apk", "rpm", "other"}:
        return "forbidden" if SYSTEM_FORBIDDEN.search(text) else "system"
    text = OVERRIDES.get(lowered, text)
    if lowered in WEAK_ALLOWED or lowered in WEB_WEAK_ALLOWED:
        return "weak"
    if FORBIDDEN.search(text) and not PERMISSIVE.search(text):
        return "forbidden"
    if WEAK_COPYLEFT.search(text) and not PERMISSIVE.search(text):
        return "weak-unlisted"
    if PERMISSIVE.search(text):
        return "allowed"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sbom", type=Path, help="CycloneDX JSON SBOM of the image")
    args = parser.parse_args()
    document = json.loads(args.sbom.read_text(encoding="utf-8"))

    counts: dict[str, int] = {}
    problems: list[str] = []
    for component in document.get("components", []):
        name = str(component.get("name", ""))
        if not name or OWN.match(name):
            continue
        kind = ecosystem(component)
        text = licenses_of(component)
        result = verdict(name, kind, text)
        counts[result] = counts.get(result, 0) + 1
        if result in {"forbidden", "weak-unlisted"} or (result == "unknown" and kind in {"pypi", "npm"}):
            problems.append(f"{kind}:{name} {component.get('version', '')}: {result} license '{text}'")

    print("image: " + ", ".join(f"{count} {name}" for name, count in sorted(counts.items())))
    for problem in problems:
        print(f"  - {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
