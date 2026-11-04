# Write migrations

Alembic, with **one branch per module**. There is no `alembic.ini`: `agnostic_kernel.migrations_runner` builds the
configuration from the installed modules (disabled ones included), and `agnostic_kernel/migrations/env.py` is shared
by every branch.

- Kernel branch: `k0001_kernel_base` creates `citext` and `pg_trgm`, Procrastinate's schema (in schema
  `procrastinate`) and `kernel_job_progress`.
- Each module ships `src/<package>/migrations/versions/` and returns it from `Module.migrations()`. Its first revision
  has `down_revision = None`, `branch_labels = ("<module>",)` and `depends_on = "k0001_kernel_base"`.
- Today every module has exactly one revision. A revision that needs another module's tables adds that module's
  revision to `depends_on`: `o0001_org` depends on `("k0001_kernel_base", "i0001_identity")` for its foreign key to
  `identity_users`.

![Migration branches: the kernel base and one branch per module; org depends on identity](images/migration-branches.svg)

## Revision ids

`<module letter><4 digits>_<slug>`. One letter per module, so ids never collide:

| Letter | Module | Head | | Letter | Module | Head |
|---|---|---|---|---|---|---|
| `k` | kernel | `k0001_kernel_base` | | `o` | org | `o0001_org` |
| `a` | audit | `a0001_audit_events` | | `p` | approvals | `p0001_approvals` |
| `b` | assistant | `b0001_assistant` | | `q` | search | `q0001_search` |
| `c` | access | `c0001_access` | | `r` | directory | `r0001_directory` |
| `d` | scheduler | `d0001_scheduler` | | `s` | settings | `s0001_settings` |
| `e` | evals | `e0001_evals` | | `t` | notifications | `t0001_notifications` |
| `g` | gateway | `g0001_gateway` | | `u` | studio | `u0001_studio` |
| `i` | identity | `i0001_identity` | | `v` | observe | `v0001_observe` |
| `n` | instances | `n0001_instances` | | `w` | service_accounts | `w0001_service_accounts` |
| | | | | `x` | sources | `x0001_sources` |

`context`, `queue` and `system` have no tables. Free letters for a new module: `f`, `h`, `j`, `l`, `m`, `y`, `z`.

## Add a revision to an existing module

`down_revision` is the module's current head; `branch_labels` and `depends_on` stay `None` (the branch already has
them). For example, a second instances revision:

```python
# backend/modules/instances/src/agnostic_instances/migrations/versions/n0002_instance_labels.py
revision = "n0002_instance_labels"
down_revision = "n0001_instances"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("inst_instances", sa.Column("labels", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
                  schema="agnostic")

def downgrade() -> None:
    op.drop_column("inst_instances", "labels", schema="agnostic")
```

Change the table model (`infrastructure/tables.py`) in the same commit; the guard tests compare the two.

Rules:

- Always pass `schema="agnostic"`; on SQLite it is mapped away.
- Stay portable between PostgreSQL and SQLite: `sa.func.current_timestamp()` for timestamp defaults,
  `JSON().with_variant(JSONB(), "postgresql")` for JSON, PostgreSQL-only statements behind
  `if is_postgresql(op.get_bind()):` (`agnostic_kernel.db`). SQLite runs `ALTER`s in batch mode (`render_as_batch`).
- Released databases are upgraded forward and expand/contract: add a column, backfill, switch readers, drop the old
  column in a later release.
- Every revision downgrades cleanly.

## Commands

```bash
uv run agnostic db upgrade                 # everything to heads
uv run agnostic db upgrade --check         # PostgreSQL: apply in one transaction, time each revision, roll back
uv run agnostic db current                 # current / heads / pending / status
uv run agnostic db downgrade gateway@base  # remove one module's tables
uv run agnostic db downgrade base          # everything (development only)
```

## Guard tests

| Test | Checks |
|---|---|
| `backend/tests/unit/test_migrations_schema.py` | the migrated SQLite schema matches the table models (Alembic `compare_metadata`: no table, column, index or type only one side has) |
| `test_migrations_match_models_on_postgres` in `backend/tests/integration/test_postgres_redis.py` | the same on PostgreSQL |
| `test_migrations_up_down_up` (same file) | upgrade → downgrade → upgrade on PostgreSQL |
| `backend/tests/unit/test_cli.py` | `db upgrade` / `downgrade <branch>@base` / `current` on SQLite, branch by branch |

A failing schema test prints the differences: add what the migration or the model is missing.

## Pre-release databases

Databases from before the first release are recreated, not upgraded. One migrated by an older build can carry
revisions this code doesn't ship; `/readyz` and `agnostic config check --connect` then report "unknown revision in
the database". Recreate it:

```bash
just nuke && just up && just migrate
```

The upgrade drill (`just upgrade-drill`, `scripts/upgrade_drill.sh`) upgrades databases from every commit listed in
`deploy/upgrade-milestones.txt`. The list starts with the first release; while it is empty the drill exits 0 with
"no milestones".

## Upgrading Procrastinate

`k0001_kernel_base` applies a frozen copy of Procrastinate 3.10.0's `schema.sql`. When the pinned Procrastinate
version changes, add a kernel revision that applies its migration scripts (`procrastinate/sql/migrations/`) with
`search_path` set to `procrastinate`; never edit `k0001`.
