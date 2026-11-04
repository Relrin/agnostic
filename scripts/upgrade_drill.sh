#!/usr/bin/env bash
# Upgrade drill: for every milestone in deploy/upgrade-milestones.txt, build a database the way that version left
# it (migrations + bootstrap), then upgrade it with the current code and check that everything still answers.
#
#   AGNOSTIC_DRILL_DATABASE_URL=postgresql://agnostic:agnostic@localhost:5432/postgres \
#   AGNOSTIC_REDIS__URL=redis://localhost:6379/0 scripts/upgrade_drill.sh
#
# Each milestone gets its own database (created and dropped here) and a git worktree under .drill/.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
if ! grep -qvE '^[[:space:]]*(#|$)' "${root}/deploy/upgrade-milestones.txt"; then
  echo "no milestones in deploy/upgrade-milestones.txt: nothing to upgrade from"
  exit 0
fi
admin_url="${AGNOSTIC_DRILL_DATABASE_URL:?set AGNOSTIC_DRILL_DATABASE_URL to a PostgreSQL URL with CREATEDB rights}"
work="${root}/.drill"
mkdir -p "${work}"
export AGNOSTIC_ENV=test AGNOSTIC_LOG__LEVEL=WARNING AGNOSTIC_LOG__FORMAT=console
failures=0

psql_admin() { uv run --project "${root}/backend" python - "$admin_url" "$1" <<'PY'
import sys

import psycopg

with psycopg.connect(sys.argv[1], autocommit=True) as connection:
    connection.execute(sys.argv[2])
PY
}

while read -r commit label; do
  [[ -z "${commit}" || "${commit}" == \#* ]] && continue
  short="${commit:0:9}"
  database="drill_${short}"
  url="${admin_url%/*}/${database}"
  echo "== ${short} (${label})"
  psql_admin "DROP DATABASE IF EXISTS ${database}"
  psql_admin "CREATE DATABASE ${database}"
  psql_admin "ALTER DATABASE ${database} OWNER TO CURRENT_USER" || true

  tree="${work}/${short}"
  git -C "${root}" worktree add --force --detach "${tree}" "${commit}" >/dev/null 2>&1 || true
  (
    cd "${tree}/backend"
    uv sync --frozen --quiet
    AGNOSTIC_DATABASE__URL="${url}" uv run agnostic db upgrade
    # Older versions only know the sign-up-link form of bootstrap.
    AGNOSTIC_DATABASE__URL="${url}" uv run agnostic bootstrap --org-name "Drill ${short}" \
      --owner-email "owner@drill.test" --owner-name "Drill Owner" --password-stdin <<<"drill-password-${short}" \
      || AGNOSTIC_DATABASE__URL="${url}" uv run agnostic bootstrap --org-name "Drill ${short}"
  )
  if (
    cd "${root}/backend"
    export AGNOSTIC_DATABASE__URL="${url}"
    uv run agnostic db upgrade --check
    uv run agnostic migrate
    uv run agnostic db current | grep -q "up to date"
    uv run agnostic config check --connect
    uv run agnostic audit verify
    uv run agnostic secrets status
  ); then
    echo "ok: ${short} upgrades cleanly"
  else
    echo "FAILED: upgrade from ${short} (${label})"
    failures=$((failures + 1))
  fi
  git -C "${root}" worktree remove --force "${tree}" >/dev/null 2>&1 || true
  psql_admin "DROP DATABASE IF EXISTS ${database}"
done <"${root}/deploy/upgrade-milestones.txt"

exit "${failures}"
