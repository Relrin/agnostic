# The computer a coding agent gets per session: Pi and OpenCode on Node 24, plus the Python Agno's sandbox runner
# needs. Build it with `just sandbox-image`; for E2B, build a template from this same file.
#
# The container runs as uid 1000 with a read-only root filesystem (Agno's DockerSandbox), so everything a harness
# writes goes to /workspace (the project) or /runtime (HOME: configuration and native session files).
FROM node:24-bookworm-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9

ARG PI_VERSION=1.5.0
ARG OPENCODE_VERSION=1.19.5
ARG OPENAI_COMPATIBLE_VERSION=3.0.87

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python-is-python3 git ripgrep ca-certificates util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g --no-fund --no-audit \
        "@earendil-works/pi-coding-agent@${PI_VERSION}" \
        "opencode-ai@${OPENCODE_VERSION}" \
    && npm cache clean --force

# OpenCode installs its provider packages on first use; the root filesystem is read-only at run time, so the
# OpenAI-compatible provider is installed here and copied into HOME when a sandbox is prepared.
RUN mkdir -p /opt/agnostic/opencode-cache \
    && cd /opt/agnostic/opencode-cache \
    && npm init -y >/dev/null \
    && npm install --no-fund --no-audit --omit=dev "@ai-sdk/openai-compatible@${OPENAI_COMPATIBLE_VERSION}" \
    && chown -R 1000:1000 /opt/agnostic

ENV PI_TELEMETRY=0 \
    PI_OFFLINE=1 \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    OPENCODE_DISABLE_SHARE=1 \
    NO_UPDATE_NOTIFIER=1

USER 1000
WORKDIR /workspace
