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

# Install every toolchain dependency (backend, runtime, frontend) from the lockfiles
setup:
    [ -f .env ] || cp .env.example .env
    cd backend && uv sync --locked
    cd runtime && uv sync --locked
    cd frontend && yarn install --immutable

# ---------------------------------------------------------------- dev stack

# Start PostgreSQL and Redis for development
up:
    {{compose}} up -d --wait

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

# Two reference AgentOS runtimes: dev-prod on :7777 and dev-staging on :7778 (needs `just up`)
runtimes:
    trap 'kill 0' INT TERM EXIT; \
    (cd runtime && RUNTIME_ID=dev-prod RUNTIME_NAME=dev-prod RUNTIME_PORT=7777 \
        RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@localhost:5432/agentos_prod \
        RUNTIME_REDIS_URL=redis://localhost:6379/1 uv run python -m app.main) & \
    (cd runtime && RUNTIME_ID=dev-staging RUNTIME_NAME=dev-staging RUNTIME_PORT=7778 \
        RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@localhost:5432/agentos_staging \
        RUNTIME_REDIS_URL=redis://localhost:6379/2 uv run python -m app.main) & \
    wait

# Print the effective configuration and probe every endpoint
check-config:
    cd backend && uv run agnostic config check --connect

# ---------------------------------------------------------------- quality gates

# Lint and format checks (backend, runtime, frontend)
lint:
    cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
    cd runtime && uv run ruff check . && uv run ruff format --check .
    cd frontend && yarn lint && yarn format:check && yarn constraints

# Type checks (basedpyright strict, tsc -b)
typecheck:
    cd backend && uv run basedpyright
    cd frontend && yarn typecheck

# Format everything in place
fmt:
    cd backend && uv run ruff format . && uv run ruff check --fix .
    cd runtime && uv run ruff format . && uv run ruff check --fix .
    cd frontend && yarn format

# Unit tests (no Docker needed: the backend runs on SQLite)
test:
    cd backend && uv run pytest -m "not integration and not contract" --cov=agnostic_kernel --cov-fail-under=90
    cd runtime && uv run pytest
    cd frontend && yarn test

# Integration tests on PostgreSQL + Redis (testcontainers, or the dev stack via AGNOSTIC_TEST_*_URL)
test-int:
    cd backend && uv run pytest -m integration

# Contract tests against a live runtime (start one with `just runtimes`)
test-contract url="http://127.0.0.1:7777":
    cd backend && AGNOSTIC_CONTRACT_RUNTIME_URL={{url}} uv run pytest -m contract

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

# Fail if the committed client is stale (CI)
api-check: api-gen
    git diff --exit-code -- frontend/packages/api

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

# ---------------------------------------------------------------- supply chain

# Dependency license policy
licenses:
    cd backend && uv run python ../scripts/check_python_licenses.py
    cd runtime && uv run --with pip-licenses==5.5.5 python ../scripts/check_python_licenses.py --runtime
    cd frontend && yarn licenses

# Known-vulnerability audit
audit:
    cd backend && uv run pip-audit --strict --progress-spinner off
    cd frontend && yarn npm audit --all --recursive

# Install git hooks (lint on commit, conventional commit messages)
hooks:
    cd backend && uv run pre-commit install --config ../.pre-commit-config.yaml --hook-type pre-commit --hook-type commit-msg
