# Upgrades

An upgrade is a new image, its migrations, and a restart of the API and worker containers. Migrations are
**expand/contract**: a release only adds to the schema in a way the previous release still works with; destructive
changes take two releases (stop using a column, then drop it). So the old containers keep serving while the
migrations run, and a rollback to the previous release works against the upgraded schema.

## Before you upgrade

1. Read what changed since your version (the commit history between the two `v*` tags) for new settings and
   behaviour changes.
2. Check the migrations against a copy of production (PostgreSQL only):

   ```bash
   AGNOSTIC_DATABASE__URL=postgresql://…/agnostic_copy agnostic db upgrade --check
   ```

   It applies every pending migration in one transaction, prints the time each took, and rolls everything back, so
   a migration that fails or is slow shows up here instead of during the rollout.
3. Take a backup or confirm your PITR is current.

## Upgrade

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

Roll back the image: set the previous `AGNOSTIC_IMAGE` and run `docker compose up -d`. Don't downgrade the schema:
the previous release works with it. `agnostic db downgrade` exists for development; don't use
it in production.

## Pre-release databases

Databases created by a pre-release build aren't upgraded: create a fresh database and run `agnostic migrate` and
`agnostic bootstrap` again (in development: `just nuke && just up && just migrate`). `/readyz` and
`config check --connect` report "unknown revision in the database" when they find one.

## How upgrades are tested

The upgrade drill (`scripts/upgrade_drill.sh`, nightly in CI) takes every released version listed in
`deploy/upgrade-milestones.txt`, migrates and bootstraps a database with that version's code, upgrades it with the
current code and checks it with `db upgrade --check`, `migrate`, `db current`, `config check --connect`,
`audit verify` and `secrets status`. The list starts with the first release.
