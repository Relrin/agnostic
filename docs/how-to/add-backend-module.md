# Add a backend module

Templates: `backend/modules/audit` (router, jobs, settings, migration, facade) and `backend/modules/settings` (the
smallest). This guide adds a module called `notes`.

## 1. Create the distribution

Files under `backend/modules/notes/`:

- `pyproject.toml`
- `src/agnostic_notes/`: `__init__.py`, `py.typed`, `module.py`, `settings.py`, `providers.py`, `facade.py`,
  `jobs.py`
- `src/agnostic_notes/{domain,application,infrastructure,api}/`
- `src/agnostic_notes/migrations/versions/`

```toml
# backend/modules/notes/pyproject.toml
[project]
name = "agnostic-notes"
version = "0.1.0"
requires-python = "==3.15.*"
license = "BSD-3-Clause"
dependencies = ["agnostic-kernel", "fastapi==0.162.0", "sqlalchemy[asyncio]==2.1.6"]  # exact versions only

[project.entry-points."agnostic.modules"]
notes = "agnostic_notes.module:NotesModule"

[tool.uv.sources]
agnostic-kernel = { workspace = true }

[build-system]
requires = ["uv_build==0.13.6"]
build-backend = "uv_build"
```

Add `"agnostic-notes"` to `dependencies` and `[tool.uv.sources]` in `backend/pyproject.toml`, then `uv sync`. The
workspace already includes `modules/*`.

## 2. Tables and the first migration

```python
# infrastructure/tables.py
from agnostic_kernel.db import make_metadata

class NotesBase(DeclarativeBase):
    metadata = make_metadata()            # schema "agnostic", deterministic constraint names

class NoteRow(NotesBase):
    __tablename__ = "notes_notes"         # always prefix with the module name
    id: Mapped[str] = mapped_column(String(40), primary_key=True)   # new_id("not")
    ...
```

Pick a module letter nobody uses ([migrations](migrations.md#revision-ids)), e.g. `y`, and write
`migrations/versions/y0001_notes.py` by hand. Its revision starts the module's branch:

```python
revision = "y0001_notes"
down_revision = None
branch_labels = ("notes",)
depends_on = "k0001_kernel_base"
```

`tests/unit/test_migrations_schema.py` fails until the migration creates exactly what `NoteRow` declares.

## 3. Domain, application, infrastructure

- `domain/`: frozen dataclasses and rules, standard library only.
- `application/`: use cases taking ports (`Protocol`s) in their constructor; raise `AppError` subclasses.
- `infrastructure/`: repositories over `AsyncSession`, adapters to `JobQueue` / `JobProgressReporter`.

## 4. API

```python
# api/router.py  (no `from __future__ import annotations` here; see backend-kernel.md)
router = APIRouter(route_class=DishkaRoute)

@router.get("/notes")
async def list_notes(params: Annotated[PageParams, Depends(page_params)],
                     use_case: FromDishka[ListNotes]) -> Page[NoteOut]: ...
```

Operation ids come from the module tag and the function name (`notes_list_notes`).

## 5. Wiring and the module object

```python
class NotesProvider(Provider):
    scope = Scope.REQUEST
    repository = provide(SqlNoteRepository, provides=NoteRepository)
    list_notes = provide(ListNotes)

class NotesModule(BaseModule):
    name = "notes"
    version = "0.1.0"
    depends_on = ()

    def provide(self): return (NotesProvider(),)
    def routers(self): return (RouterSpec(router=router, prefix="/notes", tags=("notes",)),)
    def metadata(self): return NotesBase.metadata
    def migrations(self): return Path(__file__).with_name("migrations") / "versions"
    def scopes(self): return (ScopeDecl("notes:read", "See notes"),)
```

Routes for signed-in people take `principal: FromDishka[Principal]` and check scopes with
`await authorizer.require(principal, "notes:read")` (`Authorizer` from `agnostic_kernel.auth`). Record changes with
`AuditLog.record(...)` from `agnostic_audit.facade`, declare the actions in `audit_actions()`, and add `"audit"` to
`depends_on`. Jobs: [background jobs](background-jobs.md); assistant tools: [add an assistant tool](add-assistant-tool.md).

## 6. Boundaries

In `backend/pyproject.toml`:

- add the module's three `[tool.importlinter]` contracts (copy the `audit` ones: layers, pure domain, "other modules
  use notes only through its facade");
- add `agnostic_notes` to `root_packages`, to the other modules' facade contracts, to `known-first-party` and to
  `[tool.coverage.run] source`.

Other modules import only `agnostic_notes.facade`. When a dependency would point the wrong way, declare a port in
the lower module's facade and provide it from the higher one ([module system](../architecture/module-system.md)).

## 7. Verify

```bash
cd backend && uv sync
uv run agnostic modules list        # notes is enabled
uv run agnostic db upgrade          # creates notes_notes
just api-gen                        # TypeScript client and docs/reference/api.md gain the notes endpoints
just check
```
