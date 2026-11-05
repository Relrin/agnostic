#!/usr/bin/env bash
# Export `runtime/` as the `agnostic-runtime` template repository: the reference AgentOS app together with the
# agnostic-bridge source it installs. The bridge isn't on a package index, so the tree keeps this repository's
# layout (`runtime/` next to `bridge/`): the path dependency, uv.lock and the image build work unchanged.
#
#   scripts/export_runtime_template.sh 0.1.0
#
# Writes dist/agnostic-runtime-<version>/ (a ready-to-push repository tree) and its tarball.
set -euo pipefail

version="${1:?usage: export_runtime_template.sh VERSION}"
root="$(cd "$(dirname "$0")/.." && pwd)"
out="${root}/dist/agnostic-runtime-${version}"
rm -rf "${out}"
mkdir -p "${out}"

for dir in runtime bridge; do
  (cd "${root}/${dir}" && git ls-files -z) | while IFS= read -r -d '' file; do
    mkdir -p "${out}/${dir}/$(dirname "${file}")"
    cp "${root}/${dir}/${file}" "${out}/${dir}/${file}"
  done
done
cp "${root}/LICENSE" "${out}/LICENSE"

python3 - "${out}/runtime" "${version}" <<'PY'
import re
import sys
from pathlib import Path

runtime, version = Path(sys.argv[1]), sys.argv[2]
for name, pattern in (
    ("pyproject.toml", r'(?m)^(version = )"[^"]+"'),
    # The template's own (virtual) entry in the lock.
    ("uv.lock", r'(?m)(?<=^name = "agnostic-runtime"\n)(version = )"[^"]+"'),
):
    path = runtime / name
    text, count = re.subn(pattern, rf'\g<1>"{version}"', path.read_text(encoding="utf-8"), count=1)
    if count != 1:
        sys.exit(f"{path}: no version to set")
    path.write_text(text, encoding="utf-8", newline="\n")
PY

cat > "${out}/README.md" <<'README'
# agnostic-runtime

The reference Agno AgentOS app for Agnostic: see [runtime/README.md](runtime/README.md). `bridge/` is the
agnostic-bridge source the app installs; it is built into the image, not taken from a package index.

```bash
cd runtime
docker build --build-context bridge=../bridge -t my-agentos .
```
README

tar -C "$(dirname "${out}")" -czf "${out}.tar.gz" "$(basename "${out}")"
echo "wrote ${out}"
