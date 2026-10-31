# agnostic-runtime image: used by our CI contract job and as a starting point for customers. Never shipped with
# Agnostic itself.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.13.12-slim-trixie@sha256:f1927c75e81efd1e091dbd64b6c0ecaa5630b38635a3d1c04034ac636e1f94c8
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /srv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN useradd --system --uid 10001 agentos && chown -R agentos /srv
USER agentos
ENV RUNTIME_HOST=0.0.0.0 RUNTIME_PORT=7777
EXPOSE 7777
HEALTHCHECK --interval=10s --timeout=3s --retries=12 CMD ["/srv/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7777/health', timeout=2)"]
CMD ["/srv/.venv/bin/python", "-m", "app.main"]
