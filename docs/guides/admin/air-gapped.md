# Air-gapped installations

Agnostic runs without internet access. It makes no outbound calls of its own: no update checks, no telemetry, no
fonts or icons from a CDN (they are in the web build), no model calls unless you configure a model provider. Every
connection it opens goes to an endpoint you configured.

## The kit

Each release has an air-gapped kit, `agnostic-airgap-<version>.tar.gz`, built by `scripts/build_airgap_kit.sh`:

| Path | What |
|---|---|
| `image/agnostic-<version>.tar` | the `agnostic` image (`docker load`) |
| `image/signatures.json` | the image's cosign signatures, when the release was signed |
| `compose/` | `compose.yml` and `.env.example` |
| `guides/` | these guides (the image serves them in the product too) |
| `licenses/` | LICENSE and the third-party license files |
| `sbom.cdx.json` | the image's CycloneDX SBOM |
| `SHA256SUMS` | checksums of every file in the kit |
| `README.md` | the steps below |

## Mirror it

```bash
tar -xzf agnostic-airgap-0.1.0.tar.gz && cd agnostic-airgap-0.1.0
sha256sum -c SHA256SUMS
docker load -i image/agnostic-0.1.0.tar
docker tag ghcr.io/relrin/agnostic:0.1.0 registry.internal/agnostic:0.1.0
docker push registry.internal/agnostic:0.1.0
```

Then install as in [Install Agnostic](install.md) with `AGNOSTIC_IMAGE=registry.internal/agnostic:0.1.0`.

## What to configure

- **Dependencies** are your in-network endpoints: PostgreSQL, the cache, object storage, SMTP relay, IdP.
- **Git hosts** for code sources must be reachable from the API and worker (an internal Gitea, GitLab or GitHub
  Enterprise), or use local folders.
- **AI features** (Ask your OS, summaries) stay off until you configure a model provider in *Organization › AI
  features*. Point it at a model served inside the network (Ollama, vLLM or another OpenAI-compatible endpoint).
- **Building from source** offline needs mirrors of PyPI and npm: `frontend/.yarnrc.yml` has `npmRegistryServer`, and
  uv reads `UV_INDEX_URL`.

## How it is tested

The `air-gapped (egress denied)` CI workflow runs the image on a Docker network with no route out: migrations,
bootstrap, the API and a worker, sign-in, the web app and the bundled guides must all work, and the logs must show
no attempt to resolve or reach an outside host.
