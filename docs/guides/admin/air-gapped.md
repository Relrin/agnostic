# Air-gapped installations

Agnostic runs without internet access. It makes no outbound calls of its own: no update checks, no telemetry, no
fonts or icons from a CDN (they are in the web build), no model calls unless you configure a model provider. Every
connection it opens goes to an endpoint you configured.

## The kit

No kit is published: build the image on a connected machine ([Build the images](build-images.md)), then the kit
with `bash scripts/build_airgap_kit.sh 0.1.0` (`just airgap-kit 0.1.0`). It writes `dist/agnostic-airgap-<version>.tar.gz`:

| Path | What |
|---|---|
| `image/agnostic-<version>.tar` | the `agnostic` image (`docker load`) |
| `compose/` | `compose.yml` and `.env.example` |
| `guides/` | these guides (the image serves them in the product too) |
| `licenses/` | LICENSE and the third-party license files |
| `sbom.cdx.json` | the image's CycloneDX SBOM, when syft was installed on the build machine |
| `SHA256SUMS` | checksums of every file in the kit |
| `README.md` | the steps below |

## Bring it in and mirror it

```bash
tar -xzf agnostic-airgap-0.1.0.tar.gz && cd agnostic-airgap-0.1.0
sha256sum -c SHA256SUMS
docker load -i image/agnostic-0.1.0.tar
docker tag agnostic:0.1.0 registry.internal/agnostic:0.1.0
docker push registry.internal/agnostic:0.1.0
```

Then install as in [Install Agnostic](install.md) with `AGNOSTIC_IMAGE=registry.internal/agnostic:0.1.0`.

## What to configure

- **Dependencies** are your in-network endpoints: PostgreSQL, the cache, object storage, SMTP relay, IdP.
- **Git hosts** for code sources must be reachable from the API and worker (an internal Gitea, GitLab or GitHub
  Enterprise), or use local folders.
- **AI features** (Ask your OS, summaries) stay off until you configure a model provider in *Organization › AI
  features*. Point it at a model served inside the network (Ollama, vLLM or another OpenAI-compatible endpoint).
- **Building the image** needs PyPI and npm: build it on a connected machine and bring it in with the kit. Running
  the code outside Docker offline needs mirrors of PyPI and npm: `frontend/.yarnrc.yml` has `npmRegistryServer`, and
  uv reads `UV_INDEX_URL`.

## Check it yourself

`bash scripts/check_airgap.sh agnostic:0.1.0` (`just airgap-check`) runs the image on a Docker network with no route
out: migrations, bootstrap, the API and a worker, sign-in, the web app and the bundled guides must all work, and the
logs must show no attempt to resolve or reach an outside host. Run it on the build machine before making the kit.
