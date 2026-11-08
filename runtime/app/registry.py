"""What Studio may compose with on this runtime: tools, models, schemas, step functions, a memory manager and
databases passed explicitly."""

from agno.db.base import BaseDb
from agno.memory import MemoryManager
from agno.registry import Registry

from app.functions import ALL_FUNCTIONS
from app.models.mock import MockModel
from app.schemas import SCHEMAS
from app.tools import ALL_TOOLS

MEMORY_MANAGER_ID = "support-memory"

# GET /registry lists models by id, so each preset has its own.
MODEL_PRESETS = [
    MockModel(id="agnostic-mock", persona="studio"),
    MockModel(id="mock-precise", persona="precise", temperature=0.2),
    MockModel(id="mock-creative", persona="creative", temperature=0.9),
    # For coding agents built in Studio: writes outputs/hello.md with the harness's own tools, offline.
    MockModel(id="mock-coder", persona="coder"),
]


def build_memory_manager(db: BaseDb | None) -> MemoryManager:
    return MemoryManager(
        id=MEMORY_MANAGER_ID,
        name=MEMORY_MANAGER_ID,
        model=MockModel(persona="memory"),
        db=db,
    )


def build_registry(db: BaseDb) -> Registry:
    return Registry(
        name="agnostic-runtime",
        description="Sample domain from the Agnostic prototype",
        tools=list(ALL_TOOLS),
        models=list(MODEL_PRESETS),
        schemas=list(SCHEMAS),
        functions=list(ALL_FUNCTIONS),
        memory_managers=[build_memory_manager(db)],
        dbs=[db],
    )
