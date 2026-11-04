"""License policy check for Python dependencies.

Runs inside a uv environment (`just licenses`) and classifies every installed distribution:

- allowed: permissive licenses (MIT, BSD, Apache-2.0, ISC, PSF, MPL is *not* here; see below);
- weak copyleft (MPL-2.0, LGPL, EPL), allowed unmodified only when reviewed and listed in WEAK_ALLOWED;
- forbidden in anything we ship: GPL, AGPL, SSPL, BSL, RSAL, Commons Clause;
- unknown: metadata we can't classify; fails until added to OVERRIDES after a manual check.

Exit code 1 on any forbidden, unknown or unreviewed weak-copyleft distribution. ``--write FILE`` also writes the
third-party notices (name, version, license, project URL and the license text each distribution ships) for
everything that passed: the ``agnostic`` image carries that file under ``/licenses``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PERMISSIVE = re.compile(
    r"\b(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|Zlib|0BSD|Unlicense|PostgreSQL|"
    r"Historical Permission Notice|HPND|CC0|Public Domain|MIT-CMU|Boost)\b",
    re.IGNORECASE,
)
WEAK_COPYLEFT = re.compile(r"\b(MPL|Mozilla Public License|LGPL|Lesser General Public|EPL|Eclipse Public)\b", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"\b(AGPL|Affero|SSPL|Server Side Public|BSL|Business Source|RSAL|Commons Clause)\b|"
    r"(?<!Lesser )\bGNU General Public License\b|\bGPL(?!.*Lesser)\b",
    re.IGNORECASE,
)

# Distributions whose metadata doesn't state the license clearly; each entry was checked by hand.
OVERRIDES: dict[str, str] = {
    "cel-python": "Apache-2.0",  # metadata empty; bundled LICENSE is Apache 2.0 (checked for 0.5.0)
}

# Weak-copyleft dependencies reviewed and allowed unmodified (name -> license). Adding one needs a reviewer.
WEAK_ALLOWED = {
    "psycopg": "LGPL-3.0",
    "psycopg-binary": "LGPL-3.0",
    "psycopg-pool": "LGPL-3.0",
    "certifi": "MPL-2.0",
    "pathspec": "MPL-2.0",
    "hypothesis": "MPL-2.0",
}

# Tooling that only runs the check itself. Our own distributions (``agnostic-*``, BSD-3-Clause) are skipped by name.
SKIP = {"pip", "setuptools", "wheel", "pip-licenses", "prettytable", "wcwidth"}
OWN_PREFIX = "agnostic-"


def installed_licenses(*, with_texts: bool = False) -> list[dict[str, str]]:
    command = [sys.executable, "-m", "piplicenses", "--format=json", "--from=mixed", "--with-system", "--with-urls"]
    if with_texts:
        command += ["--with-license-file", "--no-license-path", "--with-notice-file"]
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603
    return json.loads(output)


def write_notices(path: Path, packages: list[dict[str, str]]) -> None:
    lines = [
        "# Third-party software (Python)",
        "",
        "Distributions installed in this image, with the license each declares and the license text it ships.",
        "",
    ]
    for package in sorted(packages, key=lambda item: item["Name"].lower()):
        license_name = OVERRIDES.get(package["Name"].lower(), package["License"])
        lines += [f"## {package['Name']} {package['Version']}", "", f"License: {license_name}"]
        if package.get("URL") and package["URL"] != "UNKNOWN":
            lines.append(f"Project: {package['URL']}")
        for field in ("LicenseText", "NoticeText"):
            text = package.get(field, "").strip()
            if text and text != "UNKNOWN":
                lines += ["", "```text", text, "```"]
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def classify(name: str, license_text: str) -> str:
    text = OVERRIDES.get(name.lower(), license_text)
    if name.lower() in WEAK_ALLOWED:
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
    parser.add_argument("--runtime", action="store_true", help="checking agnostic-runtime (dev/CI only, not shipped)")
    parser.add_argument("--write", type=Path, help="also write the third-party notices (Markdown) to this file")
    args = parser.parse_args()

    problems: list[str] = []
    counts: dict[str, int] = {}
    shipped: list[dict[str, str]] = []
    for package in installed_licenses(with_texts=args.write is not None):
        name = package["Name"]
        if name.lower() in SKIP or name.lower().startswith(OWN_PREFIX):
            continue
        shipped.append(package)
        verdict = classify(name, package["License"])
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict in {"forbidden", "weak-unlisted", "unknown"}:
            problems.append(f"{name} {package['Version']}: {verdict} license '{package['License']}'")

    scope = "agnostic-runtime" if args.runtime else "backend"
    print(f"{scope}: " + ", ".join(f"{count} {verdict}" for verdict, count in sorted(counts.items())))
    for problem in problems:
        print(f"  - {problem}")
    if args.write is not None and not problems:
        write_notices(args.write, shipped)
        print(f"wrote {args.write}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
