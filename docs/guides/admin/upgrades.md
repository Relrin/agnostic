# Upgrades

Upgrades are rolling and need no downtime. Migrations are **expand/contract**: a release only adds to the schema
in a way the previous release still works with; destructive changes take two releases (stop using a column, then
drop it). So the old pods keep serving while the new ones start, and a rollback to the previous release works
against the upgraded schema.

## Before you upgrade

1. Read the release notes for new settings and behaviour changes.
2. Check the migrations against a copy of production (PostgreSQL only):

   ```bash
   AGNOSTIC_DATABASE__URL=postgresql://…/agnostic_copy agnostic db upgrade --check
   ```

   It applies every pending migration inside one transaction, prints the time each one took, and rolls everything
   back. A migration that fails or takes too long shows up here instead of during the rollout. SQLite can't do this:
   its driver commits schema changes right away.
3. Take a backup or confirm your PITR is current.

## With Helm

```bash
helm upgrade agnostic deploy/helm/agnostic -f values.yaml --version 1.0.1
```

The migrate Job runs as a pre-upgrade hook; Helm waits for it before rolling the Deployments. API pods roll one at a
time with `maxUnavailable: 0` and drain streams for up to 60 seconds; workers finish their current jobs (up to 120
seconds). If the Job fails, nothing else changes: read its logs (`kubectl logs job/agnostic-migrate`), fix, rerun.

## With Compose

```bash
docker compose pull
docker compose up -d       # migrate runs first, api and worker start after it succeeds
```

## After you upgrade

```bash
agnostic db current        # "up to date"
agnostic config check --connect
```

The System page shows the running version of every module.

## Rolling back

Roll back the image (`helm rollback`, or the previous `AGNOSTIC_IMAGE`). Don't downgrade the schema: the previous
release works with it. `agnostic db downgrade` exists for development and should only be used in production on the
advice of the release notes.

## How upgrades are tested

The upgrade drill (`scripts/upgrade_drill.sh`, nightly in CI) builds a database the way each pre-1.0 milestone left
it, migrated and bootstrapped with that milestone's code, then upgrades it with the current code and checks it with
`db upgrade --check`, `migrate`, `config check --connect`, `audit verify` and `secrets status`. The milestones are
listed in `deploy/upgrade-milestones.txt`.
