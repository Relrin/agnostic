#!/usr/bin/env bash
# Export `runtime/` as the `agnostic-runtime` template repository: the reference AgentOS app, depending on the
# published agnostic-bridge instead of this repository's ../bridge.
#
#   scripts/export_runtime_template.sh 1.0.0 [bridge-version]
#
# Writes dist/agnostic-runtime-<version>/ (a ready-to-push repository tree) and its tarball. Run `uv lock` in the
# exported tree against your package index before the first commit there.
set -euo pipefail

version="${1:?usage: export_runtime_template.sh VERSION [BRIDGE_VERSION]}"
bridge_version="${2:-${version}}"
root="$(cd "$(dirname "$0")/.." && pwd)"
out="${root}/dist/agnostic-runtime-${version}"
rm -rf "${out}"
mkdir -p "${out}"

(cd "${root}/runtime" && git ls-files -z) | while IFS= read -r -d '' file; do
  mkdir -p "${out}/$(dirname "${file}")"
  cp "${root}/runtime/${file}" "${out}/${file}"
done
cp "${root}/LICENSE" "${out}/LICENSE"

python3 - "${out}/pyproject.toml" "${bridge_version}" "${version}" <<'PY'
import re
import sys
from pathlib import Path

path, bridge, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
text = re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1)
text = re.sub(r'"agnostic-bridge==[^"]+"', f'"agnostic-bridge=={bridge}"', text)
# The path source only exists inside the Agnostic repository.
text = re.sub(r"(?m)^\[tool\.uv\.sources\]\n(?:#.*\n)*agnostic-bridge = .*\n\n?", "", text)
path.write_text(text, encoding="utf-8")
PY
rm -f "${out}/uv.lock"

tar -C "$(dirname "${out}")" -czf "${out}.tar.gz" "$(basename "${out}")"
echo "wrote ${out} (run 'uv lock' there against your index)"
