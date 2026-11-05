# Build the images

Agnostic publishes no container images. A release is a git tag (`v0.1.0`); you build the images from the tagged
source with `scripts/build_images.sh` and run them from your own host or registry. CI builds, smoke tests and scans
the same Dockerfile on every change, so a tag builds the way CI tested it.

| Image | Built from | For |
|---|---|---|
| `agnostic` | `Dockerfile` at the repository root | the control plane: `api`, `worker`, `migrate`, and the web app the API serves |
| `agnostic-runtime` | `runtime/Dockerfile`, with `bridge/` as a named build context | the reference AgentOS app; optional, any AgentOS 3.1.x app with `agnostic-bridge` works |

## Requirements

- Docker Engine 23 or newer, or Docker Desktop: the Dockerfiles need BuildKit (the default builder since 23), and
  `docker buildx` for images of another architecture.
- During the build, access to Docker Hub (the Python and Node base images), `ghcr.io` (the uv image), PyPI and
  `registry.npmjs.org`.
- A few GB of free disk for the build cache. The web app build is the slowest step.

What gets installed is fixed by the tag: base images are pinned by digest, Python packages by `backend/uv.lock`, npm
packages by `frontend/yarn.lock`. The one exception is the operating system: the image applies the Debian security
updates available when you build, so rebuilding a tag later picks up OS fixes published since.

## Build `agnostic`

```bash
git clone --branch v0.1.0 --depth 1 https://github.com/Relrin/agnostic.git
cd agnostic
bash scripts/build_images.sh                 # or: just images
```

This builds `agnostic:0.1.0` (the version comes from the checkout), labels it with the version and commit
(`org.opencontainers.image.version` and `.revision`), and runs the checks CI runs on every image: it starts with a
read-only root filesystem, runs as uid 10001 and carries its license files. It warns when the checkout isn't the
release tag or has uncommitted changes. `bash scripts/build_images.sh --help` lists the options.

Then set `AGNOSTIC_IMAGE=agnostic:0.1.0` in `deploy/compose/.env` and continue with
[Install Agnostic](install.md).

### Without the script

Where bash isn't available, the same build and checks:

```bash
docker build -t agnostic:0.1.0 --build-arg VERSION=0.1.0 --build-arg REVISION="$(git rev-parse HEAD)" .
docker run --rm --read-only --tmpfs /tmp agnostic:0.1.0 --help
docker run --rm --read-only --tmpfs /tmp -e AGNOSTIC_ENV=test agnostic:0.1.0 modules list
docker run --rm --entrypoint id agnostic:0.1.0 -u                    # 10001: it runs as non-root
docker run --rm --entrypoint ls agnostic:0.1.0 /licenses             # LICENSE and THIRD_PARTY_LICENSES-*
```

## Check it without a route out

```bash
bash scripts/check_airgap.sh                 # or: just airgap-check; default image agnostic:<version>
```

It runs the image with PostgreSQL and Redis on a Docker network that has no route out, then checks that migrations,
bootstrap, the API and a worker, sign-in, the web app and the bundled guides work, and that nothing tried to reach an
outside host. Everything it starts is named `agnostic-airgap-*` and removed when it ends.

## Build once, run elsewhere

Building on the host that runs Agnostic needs nothing more. To build on one machine and run on others, push to a
registry you run (Harbor, the GitLab or Gitea container registry, `registry:2`…):

```bash
docker login registry.internal
docker buildx create --name agnostic --use      # once: a builder that can produce multi-platform images
bash scripts/build_images.sh --registry registry.internal --platform linux/amd64,linux/arm64 --push
```

That pushes `registry.internal/agnostic:0.1.0` and prints its digest; add `--runtime` to push
`registry.internal/agnostic-runtime` too, and `--latest` to also move `:latest`. A multi-platform build can't be loaded into the local
Docker image store, which is why it needs `--push`.

Leave out the platforms you don't run. Building `linux/arm64` on an amd64 host (or the reverse) runs under QEMU
emulation, which is slow; install it with `docker run --privileged --rm tonistiigi/binfmt --install all`, or build on
a host of that architecture.

Deploy by digest once you trust a build: `AGNOSTIC_IMAGE=registry.internal/agnostic@sha256:<digest>`.

Without a registry, move the image as a file:

```bash
docker save agnostic:0.1.0 | gzip > agnostic-0.1.0.tar.gz     # on the build host
docker load -i agnostic-0.1.0.tar.gz                          # on the target host
```

For hosts without internet access, the [air-gapped kit](#the-air-gapped-kit) bundles the image with everything else
an installation needs.

## Scan, SBOM and signing

Optional, and the same tools CI uses. Run them from the repository checkout:

```bash
# Known vulnerabilities (fails on fixable HIGH or CRITICAL findings)
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/.github/trivy-secret.yaml:/trivy-secret.yaml:ro" aquasec/trivy:0.76.1 \
  image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed --secret-config /trivy-secret.yaml agnostic:0.1.0

# CycloneDX SBOM, checked against the project's license policy
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/out" anchore/syft:v1.56.0 \
  agnostic:0.1.0 -o cyclonedx-json=/out/sbom.cdx.json
docker run --rm --entrypoint cat agnostic:0.1.0 /licenses/THIRD_PARTY_LICENSES-python.md > notices-python.md
python3 scripts/check_sbom_licenses.py sbom.cdx.json --notices notices-python.md
```

To sign what you pushed with your own key, and verify it before deploying:

```bash
cosign generate-key-pair                                         # once; keep cosign.key in your secret store
cosign sign --key cosign.key registry.internal/agnostic@sha256:<digest>
cosign verify --key cosign.pub registry.internal/agnostic@sha256:<digest>
```

[Hardening](hardening.md#build-and-pin-the-image) covers enforcing the signature at deploy time.

## Build `agnostic-runtime`

The reference AgentOS app installs the bridge from the repository:

```bash
bash scripts/build_images.sh --runtime-only  # agnostic-runtime:0.1.0; --runtime builds both images
```

Without the script, from the repository root: `docker build --build-context bridge=bridge -t agnostic-runtime:0.1.0
runtime`.

It is a starting point for your own runtime: its settings, and how to add `agnostic-bridge` to an AgentOS app you
already have, are in [Bridge and runtime](../bridge-and-runtime.md).

## The air-gapped kit

After building `agnostic:0.1.0`, on the same machine:

```bash
bash scripts/build_airgap_kit.sh 0.1.0     # or: just airgap-kit 0.1.0
```

It writes `dist/agnostic-airgap-0.1.0.tar.gz`: the image archive, the Compose example, these guides, the licenses, an
SBOM when [syft](https://github.com/anchore/syft) is installed, and checksums. Pass an image reference as the second
argument to package a different tag. Installing from it: [Air-gapped installations](air-gapped.md).

## Building behind a proxy or mirror

The base images are build arguments, so they can come from your registry's mirror:

```bash
docker build \
  --build-arg PYTHON_IMAGE=registry.internal/library/python:3.15.2-slim-trixie@sha256:<digest> \
  --build-arg NODE_IMAGE=registry.internal/library/node:26.13.0-trixie-slim@sha256:<digest> \
  --build-arg UV_IMAGE=registry.internal/astral-sh/uv:0.13.6@sha256:<digest> \
  -t agnostic:0.1.0 .
```

Use the digests from the `ARG` lines at the top of the `Dockerfile`, so a mirror can't change what you build. Python
and npm packages are still fetched during the build. Where the build host can't reach PyPI or npm, build on a
connected machine and bring the image in as a file or with the air-gapped kit.

## For each release

Check out the new tag, build with the new version, and keep the previous image until the upgrade is done: rolling
back is pointing `AGNOSTIC_IMAGE` at it again ([Upgrades](upgrades.md)).
