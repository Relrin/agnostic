#!/usr/bin/env bash
# Seeds the dev Gitea for code sources: an admin (agnostic / agnostic-dev-password), the northwind organization, the
# northwind/agent-platform repository holding the reference runtime's app (agents/, teams/, workflows/,
# registry.py at the root, as the default path mappings expect) and an access token for a Gitea connection.
#
#   just git-up && just gitea-seed
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/deploy/dev/compose.yml" --profile git)
URL="http://localhost:${AGNOSTIC_DEV_GITEA_PORT:-3000}"
USER_NAME="agnostic"
PASSWORD="agnostic-dev-password"

"${COMPOSE[@]}" exec -T gitea gitea admin user create --admin --username "$USER_NAME" --password "$PASSWORD" \
  --email agnostic@localhost.company --must-change-password=false >/dev/null 2>&1 || true

api() {
  curl -fsS -u "$USER_NAME:$PASSWORD" -H "Content-Type: application/json" "$@"
}

api -X POST "$URL/api/v1/orgs" -d '{"username": "northwind"}' >/dev/null 2>&1 || true
api -X POST "$URL/api/v1/orgs/northwind/repos" \
  -d '{"name": "agent-platform", "default_branch": "main", "private": true}' >/dev/null 2>&1 || true

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -r "$ROOT/runtime/app/agents" "$ROOT/runtime/app/teams" "$ROOT/runtime/app/workflows" "$WORK/"
cp "$ROOT/runtime/app/registry.py" "$WORK/"
find "$WORK" -name "__pycache__" -type d -prune -exec rm -rf {} +
(
  cd "$WORK"
  git init -q --initial-branch main
  git -c user.name="Lena Ito" -c user.email="lena@northwind.test" add -A
  git -c user.name="Lena Ito" -c user.email="lena@northwind.test" commit -q -m "Agents, teams and workflows"
  git push -q --force "http://$USER_NAME:$PASSWORD@localhost:${AGNOSTIC_DEV_GITEA_PORT:-3000}/northwind/agent-platform.git" main
)

TOKEN_NAME="agnostic-dev-$(date +%s)"
TOKEN="$(api -X POST "$URL/api/v1/users/$USER_NAME/tokens" \
  -d "{\"name\": \"$TOKEN_NAME\", \"scopes\": [\"write:repository\", \"read:user\", \"read:organization\"]}" |
  python -c 'import json, sys; print(json.load(sys.stdin)["sha1"])')"

cat <<EOF
Gitea is ready at $URL (admin: $USER_NAME / $PASSWORD).

Connect it in Studio › Code sources › Connect source:
  provider   Gitea
  server URL $URL
  token      $TOKEN
  repository northwind/agent-platform · main

For webhooks, start the API with AGNOSTIC_SOURCES__WEBHOOK_BASE_URL=http://host.docker.internal:8000
EOF
