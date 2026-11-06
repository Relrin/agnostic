#!/usr/bin/env bash
# Build the air-gapped kit: everything an installation without internet access needs, in one tarball. Run it on a
# connected machine after building the image (docs/guides/admin/build-images.md); nothing is downloaded from a
# release.
#
#   scripts/build_airgap_kit.sh 0.2.0 [image-ref]     # image-ref defaults to the local tag agnostic:0.2.0
#
# Contents: the `agnostic` image (`docker save` archive), the Compose example, the guides, LICENSE and
# THIRD_PARTY_LICENSES, the image SBOM when syft is installed, and SHA256SUMS. Needs docker.
set -euo pipefail

version="${1:?usage: build_airgap_kit.sh VERSION [IMAGE]}"
image="${2:-agnostic:${version}}"
root="$(cd "$(dirname "$0")/.." && pwd)"
out="${root}/dist/agnostic-airgap-${version}"
rm -rf "${out}"
mkdir -p "${out}/image" "${out}/compose" "${out}/licenses"

echo "image: ${image}"
if docker buildx imagetools inspect "${image}" >/dev/null 2>&1; then
  # A reference in your registry: record its manifest and pull it (this host's platform) so docker save has it.
  docker buildx imagetools inspect "${image}" --format '{{json .Manifest}}' >"${out}/image/manifest.json"
  docker pull --quiet "${image}" >/dev/null
fi
docker save "${image}" -o "${out}/image/agnostic-${version}.tar"

cp "${root}/deploy/compose/compose.yml" "${root}/deploy/compose/.env.example" "${out}/compose/"
cp -r "${root}/docs/guides" "${out}/guides"
cp "${root}/LICENSE" "${out}/licenses/"
container="$(docker create "${image}")"
docker cp "${container}:/licenses/." "${out}/licenses/" >/dev/null
docker rm "${container}" >/dev/null

if command -v syft >/dev/null; then
  syft "${image}" -o cyclonedx-json="${out}/sbom.cdx.json" >/dev/null
fi

cat >"${out}/README.md" <<EOF
# Agnostic ${version}: air-gapped kit

1. Load the image and push it to your registry:

       docker load -i image/agnostic-${version}.tar
       docker tag ${image} registry.internal/agnostic:${version}
       docker push registry.internal/agnostic:${version}

2. Install with Compose (\`compose/\`, AGNOSTIC_IMAGE=registry.internal/agnostic:${version}).
3. Follow guides/admin/install.md and guides/admin/air-gapped.md. The guides are also served in the product (Help).

Verify the files with \`sha256sum -c SHA256SUMS\`.
EOF

(cd "${out}" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)
tar -C "$(dirname "${out}")" -czf "${out}.tar.gz" "$(basename "${out}")"
echo "wrote ${out}.tar.gz"
