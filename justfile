# Agnostic task runner: `just --list` shows every recipe.
# Install just with `uv tool install rust-just==1.59.0`. Recipes run in `sh` everywhere (on Windows that's the
# sh.exe from Git for Windows) and load `.env` from the repository root.

set dotenv-load := true
set windows-shell := ["sh", "-cu"]
set shell := ["sh", "-cu"]

compose := "docker compose -f deploy/dev/compose.yml"

# List recipes
default:
    @just --list

# Install every toolchain dependency (backend, runtime, bridge, frontend) from the lockfiles
setup:
    [ -f .env ] || cp .env.example .env
    cd backend && uv sync --locked
    cd runtime && uv sync --locked
    cd bridge && uv sync --locked
    cd frontend && yarn install --immutable

# ---------------------------------------------------------------- dev stack

# Start PostgreSQL, Redis, Mailpit (mail UI on http://localhost:8025) and the Slack mock (http://localhost:8030)
up:
    {{compose}} up -d --wait

# Start the dev Gitea (code sources against a real git host)
git-up:
    {{compose}} --profile git up -d --wait gitea

# Create the Gitea admin, the northwind/agent-platform repository (the reference runtime's app) and a token
gitea-seed:
    bash deploy/dev/gitea/seed.sh

# Start the dev Ollama and pull a small model for Ask your OS (model=…: any Ollama model with tool calling)
ai-up model="qwen3:8b":
    {{compose}} --profile ai up -d --wait ollama
    {{compose}} exec ollama ollama pull {{model}}

# Stop the dev stack (data volume is kept; `just nuke` deletes it)
down:
    {{compose}} down

# Stop the dev stack and delete its data
nuke:
    {{compose}} down --volumes

# Apply database migrations (kernel + every installed module)
migrate:
    cd backend && uv run agnostic db upgrade

# API + worker (auto-reload) and the Vite dev server; open http://localhost:5173
dev:
    trap 'kill 0' INT TERM EXIT; \
    (cd backend && uv run agnostic dev) & \
    (cd frontend && yarn dev) & \
    wait

# API only (port 8000)
api:
    cd backend && uv run agnostic api --reload

# Background worker only
worker:
    cd backend && uv run agnostic worker

# Web app only (port 5173, proxies /api to :8000)
web:
    cd frontend && yarn dev

# Each runtime verifies control-plane JWTs once `just seed` has written runtime/.jwt/<id>.pem; restart after it does.
# Two reference AgentOS runtimes: dev-prod on :7777 and dev-staging on :7778 (needs `just up`)
runtimes:
    trap 'kill 0' INT TERM EXIT; \
    for id in dev-prod dev-staging; do \
        if [ -f "runtime/.jwt/$id.pem" ]; then echo "$id: JWT authorization on (key: runtime/.jwt/$id.pem)"; \
        else echo "$id: auth_mode=none until 'just seed' writes runtime/.jwt/$id.pem"; fi; \
    done; \
    prod_key="$(cat runtime/.jwt/dev-prod.pem 2>/dev/null || true)"; \
    staging_key="$(cat runtime/.jwt/dev-staging.pem 2>/dev/null || true)"; \
    (cd runtime && RUNTIME_ID=dev-prod RUNTIME_NAME=dev-prod RUNTIME_PORT=7777 \
        RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@localhost:5432/agentos_prod \
        RUNTIME_REDIS_URL=redis://localhost:6379/1 JWT_VERIFICATION_KEY="$prod_key" \
        RUNTIME_JWT_ISSUER="${AGNOSTIC_INSTANCES__ISSUER:-${AGNOSTIC_HTTP__PUBLIC_URL:-}}" uv run python -m app.main) & \
    (cd runtime && RUNTIME_ID=dev-staging RUNTIME_NAME=dev-staging RUNTIME_PORT=7778 \
        RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@localhost:5432/agentos_staging \
        RUNTIME_REDIS_URL=redis://localhost:6379/2 JWT_VERIFICATION_KEY="$staging_key" \
        RUNTIME_JWT_ISSUER="${AGNOSTIC_INSTANCES__ISSUER:-${AGNOSTIC_HTTP__PUBLIC_URL:-}}" uv run python -m app.main) & \
    wait

# Create the org and the dev Owner (AGNOSTIC_DEV_OWNER_EMAIL/_PASSWORD); once per database, after `just migrate`
bootstrap:
    printf '%s\n' "${AGNOSTIC_DEV_OWNER_PASSWORD:-localhost-dev-password}" | (cd backend && uv run agnostic bootstrap \
        --org-name "Localhost Company" --owner-email "${AGNOSTIC_DEV_OWNER_EMAIL:-daniel@localhost.company}" \
        --owner-name "Daniel Okafor" --password-stdin)

# First run: up → migrate → dev → runtimes → bootstrap → seed → restart runtimes → seed --test
# Connect dev-prod and dev-staging to the running API and write their keys to runtime/.jwt (--test: test them)
seed *args:
    cd backend && uv run python ../scripts/dev_seed.py {{args}}

# Print the effective configuration and probe every endpoint
check-config:
    cd backend && uv run agnostic config check --connect

# ---------------------------------------------------------------- quality gates

# Lint and format checks (backend, runtime, bridge, frontend)
lint:
    cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
    cd runtime && uv run ruff check . && uv run ruff format --check .
    cd bridge && uv run ruff check . && uv run ruff format --check .
    cd frontend && yarn lint && yarn format:check && yarn constraints

# Type checks (basedpyright strict, tsc -b)
typecheck:
    cd backend && uv run basedpyright
    cd frontend && yarn typecheck

# Format everything in place
fmt:
    cd backend && uv run ruff format . && uv run ruff check --fix .
    cd runtime && uv run ruff format . && uv run ruff check --fix .
    cd bridge && uv run ruff format . && uv run ruff check --fix .
    cd frontend && yarn format

# Unit tests (no Docker needed: the backend runs on SQLite)
test:
    cd backend && uv run pytest -m "not integration and not contract and not assistant_eval" --cov=agnostic_kernel --cov-fail-under=90
    cd runtime && uv run pytest
    cd bridge && uv run pytest
    cd frontend && yarn test

# Integration tests on PostgreSQL + Redis (testcontainers, or the dev stack via AGNOSTIC_TEST_*_URL)
test-int:
    cd backend && uv run pytest -m integration

# Contract tests against a live runtime (start one with `just runtimes`)
test-contract url="http://127.0.0.1:7777":
    cd backend && AGNOSTIC_CONTRACT_RUNTIME_URL={{url}} uv run pytest -m contract

# The assistant's Q&A pairs on seeded data, asked to a real model (default: the dev Ollama from `just ai-up`)
test-assistant model="ollama:qwen3:8b" endpoint="http://localhost:11434":
    cd backend && AGNOSTIC_TEST_ASSISTANT_MODEL={{model}} AGNOSTIC_TEST_ASSISTANT_ENDPOINT={{endpoint}}         uv run pytest -m assistant_eval

# Storybook stories with axe a11y checks, then Playwright e2e
test-ui:
    cd frontend && yarn workspace @agnostic/ui storybook:test && yarn e2e

# Everything CI runs locally (except contract and e2e)
check: lint typecheck test test-int api-check licenses

# Storybook on :6006
storybook:
    cd frontend && yarn storybook

# ---------------------------------------------------------------- code generation

# Regenerate the frontend API client from the backend OpenAPI
api-gen:
    cd backend && uv run agnostic openapi --out ../frontend/packages/api/openapi.json
    cd frontend && yarn api:gen
    python3 scripts/render_api_reference.py

# Fail if the committed client (or the API reference page) is stale (CI)
api-check: api-gen
    git diff --exit-code -- frontend/packages/api docs/reference/api.md

# Regenerate the AgentOS client models from the pinned runtime's OpenAPI
agentos-client-gen:
    cd runtime && uv run python -m app.dump_openapi ../backend/packages/agnostic-agentos-client/openapi/agentos-3.1.12.json
    cd backend/packages/agnostic-agentos-client && uv run --project ../.. datamodel-codegen \
        --input openapi/agentos-3.1.12.json --input-file-type openapi \
        --output src/agnostic_agentos_client/_generated/models.py \
        --output-model-type pydantic_v2.BaseModel --target-python-version 3.14 \
        --use-standard-collections --use-union-operator --use-schema-description --field-constraints \
        --enum-field-as-literal one --allow-extra-fields --disable-timestamp --use-annotated \
        --custom-file-header '# Generated from openapi/agentos-3.1.12.json by datamodel-code-generator. Do not edit; run `just agentos-client-gen`.'

# Write agno's serialized agents and teams to backend/tests/golden (the control plane's config fixtures) and the
# code Studio generates for each of them
golden:
    cd runtime && uv run python -m app.dump_golden
    cd backend && uv run python -m agnostic_codegen tests/golden/agno-3.1

# ---------------------------------------------------------------- supply chain

# Dependency license policy
licenses:
    cd backend && uv run python ../scripts/check_python_licenses.py
    cd runtime && uv run --with pip-licenses==5.5.5 python ../scripts/check_python_licenses.py --runtime
    cd frontend && yarn licenses

# Known-vulnerability audit
audit:
    cd backend && uv export --locked --no-emit-workspace --all-groups --format requirements-txt -o .venv/requirements-audit.txt > /dev/null \
        && uv run pip-audit --strict --progress-spinner off --disable-pip --require-hashes -r .venv/requirements-audit.txt
    cd frontend && yarn npm audit --all --recursive --environment production

# Install git hooks (lint on commit, conventional commit messages)
hooks:
    cd backend && uv run pre-commit install --config ../.pre-commit-config.yaml --hook-type pre-commit --hook-type commit-msg

# ---------------------------------------------------------------- packaging & release

# Build the `agnostic` image (API, worker, migrations and the web app) from the repository root
image tag="agnostic:dev":
    docker build -t {{tag}} .

# Third-party notices (Python and web app) into dist/, as the image build writes them
notices:
    mkdir -p dist
    cd backend && uv run python ../scripts/check_python_licenses.py --write ../dist/THIRD_PARTY_LICENSES-python.md
    cd frontend && node scripts/check-licenses.mjs --write ../dist/THIRD_PARTY_LICENSES-web.md

# The air-gapped kit for a version (image archive, Compose example, guides, licenses, checksums)
airgap-kit version image="":
    bash scripts/build_airgap_kit.sh {{version}} {{image}}

# The agnostic-runtime template repository, with the agnostic-bridge source it builds
runtime-template version:
    bash scripts/export_runtime_template.sh {{version}}

# The production web build under the production CSP and Trusted Types (vite preview)
test-csp:
    cd frontend && yarn workspace @agnostic/web e2e:csp

# Query plans of the hot list queries at realistic volumes (needs Docker or AGNOSTIC_TEST_DATABASE_URL)
test-query-plans:
    cd backend && uv run pytest tests/integration/test_query_plans.py -m integration -rxX

# Upgrade every released milestone's database to the current code (needs `just up`)
upgrade-drill:
    AGNOSTIC_DRILL_DATABASE_URL="${AGNOSTIC_DRILL_DATABASE_URL:-postgresql://agnostic:agnostic@localhost:5432/agnostic}" \
        bash scripts/upgrade_drill.sh

# Back up the dev database, restore it into a copy and verify the copy
restore-drill:
    bash scripts/restore_drill.sh

# Start the dev OpenBao (Vault Transit API, key "agnostic") to try the vault master-key provider
vault-up:
    {{compose}} --profile vault up -d --wait vault
    {{compose}} exec -e BAO_TOKEN=dev-root-token vault sh -c 'bao secrets enable transit 2>/dev/null; bao write -f transit/keys/agnostic'
