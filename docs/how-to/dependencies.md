# Dependencies

## Everything is pinned exactly

| What | Where | How |
|---|---|---|
| Python packages | every `pyproject.toml` | `==` versions; `uv.lock` pins the rest (`uv sync --locked` in CI) |
| Build backend | `[build-system]` | `uv_build==0.13.6` |
| Python itself | `backend/.python-version`, `runtime/.python-version`, `bridge/.python-version` | `3.15.2`, `3.13.12`, `3.13.12` (the bridge also declares `requires-python >=3.10`; CI tests 3.13) |
| uv | `[tool.uv] required-version` | `==0.13.6` |
| JS packages | every `package.json` | exact versions (`.yarnrc.yml` `defaultSemverRangePrefix: ""`); `yarn.lock` |
| Yarn | `packageManager` + `.yarn/releases/yarn-4.18.1.cjs` | `yarnPath`, no Corepack needed |
| Node | `.nvmrc` | `26.13.0` |
| Container images | `deploy/dev/compose.yml`, `runtime/Dockerfile`, CI | tag + `@sha256` digest |
| GitHub Actions | `.github/workflows` | full commit SHA with the version in a comment |
| Git hooks | `.pre-commit-config.yaml` | exact `rev` |
| just | README | `uv tool install rust-just==1.59.0` |

`yarn constraints` fails on any range and keeps a dependency at one version across workspaces.

## Adding a dependency

```bash
# Python: in the member that imports it
cd backend && uv add --package agnostic-kernel "somepkg==1.2.3"
# JS: in the workspace that imports it
cd frontend && yarn workspace @agnostic/ui add somepkg@1.2.3
```

Then:

- `just licenses`: the license must be allowed. Weak copyleft needs review and an entry in the license scripts' allowlist.
- deptry (backend) checks that every import is declared in the right member.
- Yarn quarantines versions published in the last 24 hours (`npmMinimalAgeGate`); pick an older release if
  install says a version is quarantined.

## Upgrading

Renovate (`renovate.json`) opens grouped pull requests every Monday, pins digests, waits three days after a
release, and refreshes lockfiles monthly. Some upgrades need extra steps:

- **agno**: bump `runtime/pyproject.toml`, run `just agentos-client-gen` and `just test-contract`
  (Renovate holds it for approval).
- **TypeScript**: typescript-eslint supports TypeScript below 6.1, so they move together.
- **Procrastinate**: add a kernel migration applying its SQL migrations ([migrations](migrations.md)).
- **FastAPI / Pydantic**: run `just api-gen`; the generated client may change.

## Security audits

`just audit` (and CI's security job) audits the locked Python pins exported from `uv.lock` (our own workspace
packages aren't on PyPI) and the frontend's production dependency tree.

When an advisory hits a transitive frontend dependency whose parent hasn't released a fix, override it in
`frontend/package.json` `resolutions`, scoped to that parent (`"parent/child": "x.y.z"`).

## Python 3.15 compatibility

See for the wheel matrix. libcst has no 3.15 wheels yet and builds from source (Rust toolchain needed).
