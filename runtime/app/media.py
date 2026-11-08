"""The runtime's media storage: where run media, artefacts included, is stored and served from.

One instance per process, shared by the agents that produce artefacts and by ``AgentOS(media_storage=...)``, whose
``GET /sessions/{session_id}/media/{storage_key}`` route only serves objects of the storage it was given.
"""

from functools import lru_cache
from pathlib import Path

from agno.media.storage.local import LocalMediaStorage

from app.settings import get_settings


@lru_cache
def media_storage() -> LocalMediaStorage:
    settings = get_settings()
    return LocalMediaStorage(base_path=str(Path(settings.media_dir) / settings.id))
