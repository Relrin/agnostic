#!/usr/bin/env bash
# Build the air-gapped kit: everything an installation without internet access needs, in one tarball.
#
#   scripts/build_airgap_kit.sh 1.0.0 [image-ref]
#
# Contents: the `agnostic` image (OCI archive, both architectures when the reference is multi-arch), the Compose
# example, the guides, LICENSE and THIRD_PARTY_LICENSES, the image SBOM, cosign signatures when present, and
# SHA256SUMS. Needs docker (buildx) and, for the SBOM, syft.
set -euo pipefail

version="${1:?usage: build_airgap_kit.sh VERSION [IMAGE]}"
image="${2:-ghcr.io/relrin/agnostic:${version}}"
root="$(cd "$(dirname "$0")/.." && pwd)"
out="${root}/dist/agnostic-airgap-${version}"
rm -rf "${out}"
mkdir -p "${out}/image" "${out}/compose" "${out}/licenses"

echo "image: ${image}"
if docker buildx imagetools inspect "${image}" >/dev/null 2>&1; then
  # A pushed (possibly multi-arch) image: keep every platform in the archive.
  docker buildx imagetools inspect "${image}" --format '{{json .Manifest}}' >"${out}/image/manifest.json"
  docker pull --quiet "${image}" >/dev/null
fi
docker save "${image}" -o "${out}/image/agnostic-${version}.tar"

cp"${root}/deploy/compose/compose.yml" "${root}/deploy/compose/.env.example" "${out}/compose/"
cp -r "${root}/docs/guides" "${out}/guides"
cp "${root}/LICENSE" "${out}/licenses/"
container="$(docker create "${image}")"
docker cp "${container}:/licenses/." "${out}/licenses/" >/dev/null
docker rm "${container}" >/dev/null

if command -v syft >/dev/null; then
  syft "${image}" -o cyclonedx-json="${out}/sbom.cdx.json" >/dev/null
fi
if command -v cosign >/dev/null; then
  cosign download signature "${image}" >"${out}/image/signatures.json" 2>/dev/null || true
fi

cat >"${out}/README.md" <<EOF
# Agnostic ${version}: air-gapped kit

1. Load the image and push it to your registry:

       docker load -i image/agnostic-${version}.tar
       docker tag ${image} registry.internal/agnostic:${version}
       docker push registry.internal/agnostic:${version}

2. Install with Compose (\`compose/\`, AGNOSTIC_IMAGE=registry.internal/agnostic:${version}).
3. Follow guides/admin/install.md and guides/admin/air-gapped.md. The guides are also served in the product (Help).

Verify the files with \`sha256sum -c SHA256SUMS\`; verify the image signature with cosign against the
signatures in image/ when your policy requires it.
EOF

(cd "${out}" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)
tar -C "$(dirname "${out}")" -czf "${out}.tar.gz" "$(basename "${out}")"
echo "wrote ${out}.tar.gz"
