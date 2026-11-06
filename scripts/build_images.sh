#!/usr/bin/env bash
# Build Agnostic's container images from this checkout. Nothing is published by the project, so this is how you get
# them; see docs/guides/admin/build-images.md.
#
#   bash scripts/build_images.sh                                  # agnostic:<version>, checked, loaded into local docker
#   bash scripts/build_images.sh --runtime                        # agnostic and agnostic-runtime
#   bash scripts/build_images.sh --registry registry.internal --platform linux/amd64,linux/arm64 --push
#
# Options:
#   --version V        tag and label version (default: the version in backend/apps/agnostic-server/pyproject.toml)
#   --registry PREFIX  name the images PREFIX/agnostic and PREFIX/agnostic-runtime (default: local names)
#   --platform LIST    comma-separated platforms; more than one needs --push (a single foreign one runs under QEMU)
#   --push             build with buildx and push to the registry instead of loading into local docker
#   --runtime          also build agnostic-runtime (the reference AgentOS app, with the bridge from bridge/)
#   --runtime-only     build only agnostic-runtime
#   --latest           also tag :latest
#   --no-check         skip the smoke checks on the local agnostic image
set -euo pipefail

# Git Bash on Windows rewrites arguments that look like POSIX paths (/tmp, /licenses) before docker sees them; with
# that off, the build contexts must be native paths, which `pwd -W` gives there (plain `pwd` everywhere else).
export MSYS2_ARG_CONV_EXCL='*'
root="$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })"
version=""
registry=""
platform=""
push=false
build_agnostic=true
build_runtime=false
latest=false
check=true

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="${2:?--version needs a value}"; shift 2 ;;
    --registry) registry="${2:?--registry needs a value}"; registry="${registry%/}"; shift 2 ;;
    --platform) platform="${2:?--platform needs a value}"; shift 2 ;;
    --push) push=true; shift ;;
    --runtime) build_runtime=true; shift ;;
    --runtime-only) build_runtime=true; build_agnostic=false; shift ;;
    --latest) latest=true; shift ;;
    --no-check) check=false; shift ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage 2 >&2 ;;
  esac
done

if [ -z "${version}" ]; then
  version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "${root}/backend/apps/agnostic-server/pyproject.toml" | head -n1)"
fi
if ${push} && [ -z "${registry}" ]; then
  echo "--push needs --registry: there is nowhere to push local names to" >&2; exit 2
fi
if [[ "${platform}" == *,* ]] && ! ${push}; then
  echo "a multi-platform build can't be loaded into local docker: add --registry and --push" >&2; exit 2
fi

revision="$(git -C "${root}" rev-parse HEAD 2>/dev/null || echo unknown)"
if git -C "${root}" rev-parse -q --verify "refs/tags/v${version}" >/dev/null; then
  if [ "$(git -C "${root}" rev-parse "v${version}^{commit}")" != "${revision}" ]; then
    echo "warning: HEAD is not the v${version} tag; the image is labelled ${version} anyway" >&2
  fi
fi
if [ -n "$(git -C "${root}" status --porcelain 2>/dev/null)" ]; then
  echo "warning: the working tree has uncommitted changes; they are part of the build" >&2
fi

name() { if [ -n "${registry}" ]; then echo "${registry}/$1"; else echo "$1"; fi; }

# build NAME CONTEXT [extra docker args...]
build() {
  local image tags=() args=()
  image="$(name "$1")"
  local context="$2"
  shift 2
  tags+=(-t "${image}:${version}")
  if ${latest}; then tags+=(-t "${image}:latest"); fi
  args=(--build-arg "VERSION=${version}" --build-arg "REVISION=${revision}" "$@")
  if [ -n "${platform}" ]; then args+=(--platform "${platform}"); fi
  echo "==> ${image}:${version}${platform:+ (${platform})}"
  if ${push}; then
    docker buildx build "${args[@]}" "${tags[@]}" --push "${context}"
    docker buildx imagetools inspect "${image}:${version}" --format '{{json .Manifest.Digest}}' \
      | sed "s|^\"|    pushed ${image}@|; s|\"$||"
  else
    docker build "${args[@]}" "${tags[@]}" "${context}"
  fi
}

smoke_check() {
  local image="$1"
  echo "==> checking ${image}"
  docker run --rm --read-only --tmpfs /tmp "${image}" --help >/dev/null
  docker run --rm --read-only --tmpfs /tmp -e AGNOSTIC_ENV=test "${image}" modules list >/dev/null
  test "$(docker run --rm --entrypoint id "${image}" -u)" = "10001" || { echo "${image} doesn't run as uid 10001" >&2; exit 1; }
  docker run --rm --entrypoint ls "${image}" /licenses | grep -q THIRD_PARTY_LICENSES-python.md \
    || { echo "${image} has no third-party license files" >&2; exit 1; }
  echo "    ok: starts read-only, runs as non-root, carries its licenses"
}

if ${build_agnostic}; then
  build agnostic "${root}"
  if ${check} && ! ${push}; then smoke_check "$(name agnostic):${version}"; fi
fi
if ${build_runtime}; then
  build agnostic-runtime "${root}/runtime" --build-context "bridge=${root}/bridge"
fi

echo
if ! ${build_agnostic}; then
  if ${push}; then echo "Pushed: $(name agnostic-runtime):${version}"; else echo "Built: $(name agnostic-runtime):${version}"; fi
elif ${push}; then
  echo "Pushed. Deploy by digest: AGNOSTIC_IMAGE=$(name agnostic)@sha256:<digest above>"
else
  echo "Built. In deploy/compose/.env: AGNOSTIC_IMAGE=$(name agnostic):${version}"
fi
