"""What Studio may compose with on this runtime: tools, models and databases passed explicitly."""

from agno.db.base import BaseDb
from agno.registry import Registry

from app.models.mock import MockModel
from app.tools import ALL_TOOLS


def build_registry(db: BaseDb) -> Registry:
    return Registry(
        name="agnostic-runtime",
        description="Sample domain from the Agnostic prototype",
        tools=list(ALL_TOOLS),
        models=[MockModel(id="agnostic-mock", persona="studio")],
        dbs=[db],
    )
