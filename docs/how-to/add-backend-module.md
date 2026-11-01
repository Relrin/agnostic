# Add a backend module

Use a small existing module as the template: `backend/modules/audit` has a router, a job, settings, a migration
and a facade; `backend/modules/settings` is the smallest. This guide adds a module called `notes`.

## 1. Create the distribution

```
backend/modules/notes/
  pyproject.toml
  src/agnostic_notes/
    __init__.py  py.typed
    module.py  settings.py  providers.py  facade.py  jobs.py
    domain/  application/  infrastructure/  api/
    migrations/versions/
```

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

Add `"agnostic-notes"` to the workspace root's `dependencies` and `[tool.uv.sources]`
(`backend/pyproject.toml`), then `uv sync`. The workspace already includes `modules/*`.

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

Write `migrations/versions/n0001_notes.py` by hand or autogenerate it (see [migrations](migrations.md)). Its first
revision starts the module's branch:

```python
revision = "n0001_notes"
down_revision = None
branch_labels = ("notes",)
depends_on = "k0001_kernel_base"
```

## 3. Domain, application, infrastructure

- `domain/`: frozen dataclasses and rules, standard library only.
- `application/`: use cases taking ports (`Protocol`s) in their constructor; raise `AppError` subclasses.
- `infrastructure/`: repositories over `AsyncSession`, adapters to `JobQueue`/`JobProgressReporter`.

## 4. API

```python
# api/router.py  (no `from __future__ import annotations` here; see backend-kernel.md)
router = APIRouter(route_class=DishkaRoute)

@router.get("/notes")
async def list_notes(params: Annotated[PageParams, Depends(page_params)],
                     use_case: FromDishka[ListNotes]) -> Page[NoteOut]: ...
```

Endpoints get stable operation ids (`notes_list_notes`) from the route name and the module tag.

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

Routes that need a signed-in person take `principal: FromDishka[Principal]` and check scopes with
`await authorizer.require(principal, "notes:read")` (`Authorizer` from `agnostic_kernel.auth`). Record changes with
`AuditLog.record(...)` from `agnostic_audit.facade` and declare the action in `audit_actions()`; add `"audit"` to
`depends_on` then.

## 6. Boundaries

Add the module's three contracts to `[tool.importlinter]` in `backend/pyproject.toml` (copy the `audit` ones:
hexagonal layers, pure domain, "other modules use notes only through its facade"), and add `agnostic_notes` to
`root_packages`, the other modules' facade contracts, `known-first-party` and `[tool.coverage.run] source`. Other
modules may import only `agnostic_notes.facade`; when a dependency would point the wrong way, declare a port in the
lower module's facade and provide it from the higher one ([module system](../architecture/module-system.md)).

## 7. Verify

```bash
cd backend && uv sync
uv run agnostic modules list        # notes is enabled
uv run agnostic db upgrade          # creates notes_notes
just api-gen                        # the TypeScript client now has the notes endpoints
just check
```
