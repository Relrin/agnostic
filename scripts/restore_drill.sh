#!/usr/bin/env bash
# Restore drill (in CI on every merge to master): back up a seeded control-plane database with pg_dump, restore it
# into a fresh database, and prove the restored copy is complete and consistent: migrations current, audit hash chain
# intact, every stored secret opens with the configured master key, archived audit months verify.
#
#   AGNOSTIC_DATABASE__URL=postgresql://agnostic:agnostic@localhost:5432/agnostic \
#   AGNOSTIC_REDIS__URL=redis://localhost:6379/0 AGNOSTIC_SECRETS__MASTER_KEY=… scripts/restore_drill.sh
#
# Needs pg_dump/pg_restore/psql of the server's major version on PATH.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
source_url="${AGNOSTIC_DATABASE__URL:?set AGNOSTIC_DATABASE__URL to the database to back up}"
restored_db="agnostic_restore_drill"
restored_url="${source_url%/*}/${restored_db}"
dump="$(mktemp -d)/agnostic.dump"
cd "${root}/backend"

echo "== back up"
pg_dump --format=custom --no-owner --file "${dump}" "${source_url}"
before_events="$(psql "${source_url}" -Atc "SELECT count(*) FROM agnostic.audit_events")"

echo "== restore into ${restored_db}"
psql "${source_url%/*}/postgres" -c "DROP DATABASE IF EXISTS ${restored_db}" -c "CREATE DATABASE ${restored_db}"
pg_restore --no-owner --dbname "${restored_url}" "${dump}"

echo "== verify the restored copy"
export AGNOSTIC_DATABASE__URL="${restored_url}"
after_events="$(psql "${restored_url}" -Atc "SELECT count(*) FROM agnostic.audit_events")"
test "${before_events}" = "${after_events}" || { echo "audit events: ${before_events} before, ${after_events} after"; exit 1; }
uv run agnostic db current | grep -q "up to date"
uv run agnostic audit verify
uv run agnostic secrets status
uv run agnostic audit archives verify --all
uv run agnostic config check --connect

psql "${source_url%/*}/postgres" -c "DROP DATABASE ${restored_db}"
echo "restore drill passed (${after_events} audit events)"
