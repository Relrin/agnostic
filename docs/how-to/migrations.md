# Write migrations

Alembic with **one branch per module**:

- the kernel branch (`kernel`, base revision `k0001_kernel_base`) creates `citext` and `pg_trgm`, Procrastinate's
  schema (in schema `procrastinate`) and `kernel_job_progress`;
- each module ships `migrations/versions/` and returns it from `Module.migrations()`; its first revision has
  `branch_labels=("<module>",)` and `depends_on="k0001_kernel_base"`.

There is no `alembic.ini`: `agnostic_kernel.migrations_runner` builds the configuration from the installed
modules. Migrations cover every **installed** module, including disabled ones.

## Commands

```bash
uv run agnostic db upgrade                 # everything to head
uv run agnostic db current                 # applied revisions, heads, pending
uv run agnostic db downgrade gateway@base  # remove one module's tables
uv run agnostic db downgrade base          # everything (development only)
```

## Writing a revision

Revisions are plain Alembic scripts. Revision ids are readable: `<module letter><4 digits>_<slug>`, e.g.
`n0002_instance_labels`.

```python
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

A migration that needs another module's tables (a foreign key to `identity_users`, say) lists that module's
revision in `depends_on`, as `o0001_org` does with `i0001_identity`.

Rules:

- Always pass `schema="agnostic"`; on SQLite the engine maps it away.
- Keep revisions portable between PostgreSQL and SQLite: use `sa.func.current_timestamp()` for timestamp
  defaults and `JSON().with_variant(JSONB(), "postgresql")` for JSON. Put PostgreSQL-only statements behind
  `if is_postgresql(op.get_bind()):`. SQLite runs in batch mode (`render_as_batch`) for `ALTER`s.
- Production migrations are forward-only and expand/contract: add a column, backfill, switch readers, then drop
  the old column in a later release.
- Every revision must downgrade cleanly; the integration suite runs up → down → up on PostgreSQL, and the unit
  suite upgrades and downgrades a module branch on SQLite.

## Upgrading Procrastinate

The kernel base revision applies a frozen copy of Procrastinate 3.10.0's `schema.sql`. When the pinned
Procrastinate version changes, add a kernel revision that applies its migration scripts
(`procrastinate/sql/migrations/`) with `search_path` set to `procrastinate`; never edit `k0001`.
