# syntax=docker/dockerfile:1.12
# The `agnostic` image: the control plane's API, worker and migrations, and the web app the API serves on the same
# origin. It contains only Agnostic's code and its dependencies; Postgres, Redis, object storage, the IdP and the
# AgentOS runtimes are endpoints the deployment points it at.
#
#   docker build -t agnostic:dev .
#   docker run --read-only --tmpfs /tmp -v agnostic-data:/var/lib/agnostic --env-file .env agnostic:dev migrate
#   docker run --read-only --tmpfs /tmp -v agnostic-data:/var/lib/agnostic --env-file .env -p 8000:8000 agnostic:dev
#
# Commands: `api` (default), `worker`, `migrate`, and every other `agnostic` CLI command.

ARG PYTHON_IMAGE=python:3.15.2-slim-trixie@sha256:8c13a3f37a6a5b71498228e902c4b9f51c1f7900d49fabf71f9a650c6120e0d0
ARG NODE_IMAGE=node:26.13.0-trixie-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- web app
FROM ${NODE_IMAGE} AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/yarn.lock frontend/.yarnrc.yml ./
COPY frontend/.yarn/releases ./.yarn/releases
COPY frontend/apps ./apps
COPY frontend/packages ./packages
COPY frontend/modules ./modules
COPY frontend/scripts ./scripts
COPY frontend/tsconfig.base.json frontend/tsconfig.json ./
# Node 26 images ship neither Yarn nor corepack: run the release the repository pins (.yarnrc.yml yarnPath).
RUN printf '#!/bin/sh\nexec node /src/frontend/.yarn/releases/yarn-4.18.1.cjs "$@"\n' > /usr/local/bin/yarn \
 && chmod +x /usr/local/bin/yarn
RUN --mount=type=cache,target=/root/.yarn/berry/cache yarn install --immutable
RUN mkdir -p /out \
 && yarn build \
 && node scripts/check-licenses.mjs --write /out/THIRD_PARTY_LICENSES-web.md \
 && cp -r apps/web/dist /out/web

# ---------------------------------------------------------------- Python environment
FROM ${PYTHON_IMAGE} AS python
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/agnostic
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
COPY backend/apps ./apps
COPY backend/packages ./packages
COPY backend/modules ./modules
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable
COPY scripts/check_python_licenses.py /src/scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/agnostic/bin/python pip-licenses==5.5.5 \
 && /opt/agnostic/bin/python /src/scripts/check_python_licenses.py --write /out/THIRD_PARTY_LICENSES-python.md \
 && uv pip uninstall --python /opt/agnostic/bin/python pip-licenses prettytable wcwidth

# ---------------------------------------------------------------- runtime image
FROM ${PYTHON_IMAGE}
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="agnostic" \
      org.opencontainers.image.description="Self-hosted control plane for Agno AgentOS" \
      org.opencontainers.image.licenses="BSD-3-Clause" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/Relrin/agnostic"
# git and ssh: code sources sync through the git CLI. The app runs from /opt/agnostic and never installs packages,
# so the base image's pip (and the libraries it vendors) goes.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends git openssh-client \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall --yes --root-user-action ignore pip \
 && useradd --system --uid 10001 --home-dir /var/lib/agnostic --shell /usr/sbin/nologin agnostic \
 && mkdir -p /var/lib/agnostic && chown agnostic /var/lib/agnostic
COPY --from=python /opt/agnostic /opt/agnostic
COPY --from=web /out/web /opt/agnostic-web
COPY docs/guides /opt/agnostic-docs
COPY LICENSE /licenses/
COPY --from=python /out/THIRD_PARTY_LICENSES-python.md /licenses/
COPY --from=web /out/THIRD_PARTY_LICENSES-web.md /licenses/
ENV PATH=/opt/agnostic/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/var/lib/agnostic \
    AGNOSTIC_HTTP__HOST=0.0.0.0 \
    AGNOSTIC_HTTP__WEB_DIR=/opt/agnostic-web \
    AGNOSTIC_HTTP__DOCS_DIR=/opt/agnostic-docs \
    AGNOSTIC_SOURCES__MIRRORS_DIR=/var/lib/agnostic/sources
WORKDIR /var/lib/agnostic
USER 10001
EXPOSE 8000 9464
# Works with a read-only root filesystem: writes go to /var/lib/agnostic (a volume) and /tmp (a tmpfs).
# The API answers /healthz on 8000; the worker (no HTTP API) answers on its metrics port.
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD ["python", "-c", "import sys, urllib.request as u\nfor url in ('http://127.0.0.1:8000/healthz', 'http://127.0.0.1:9464/metrics'):\n    try:\n        u.urlopen(url, timeout=2); sys.exit(0)\n    except OSError: pass\nsys.exit(1)"]
ENTRYPOINT ["agnostic"]
CMD ["api"]
