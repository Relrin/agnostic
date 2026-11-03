"""agnostic-bridge: control-plane companion routes for an Agno AgentOS.

Install it on the AgentOS app and serve the app it returns::

    from agnostic_bridge import install

    agent_os = AgentOS(..., authorization=True)
    app = install(agent_os)  # instead of agent_os.get_app()

Routes live under ``/agnostic/v1``, are guarded by the same AgentOS auth layer as every built-in route, and need
the scopes in :data:`SCOPE_MAPPINGS` (``agent_os:admin`` passes too). The bridge keeps no state of its own; its
eval route runs AgentOS's own eval helpers, which call models and store the result in the AgentOS db; its file
provenance route reads the traces AgentOS already stores; its workers route describes the replica that answers; its
events route reads the approvals and schedule runs AgentOS already stores.
"""

from agnostic_bridge._app import BRIDGE_PREFIX, SCOPE_MAPPINGS, create_router, install
from agnostic_bridge._capabilities import BridgeCapabilities, BridgeFeatures, BridgeQueueFeatures, __version__
from agnostic_bridge._evals import BridgeEvalRun, BridgeEvalRunInput
from agnostic_bridge._events import EVENTS_PATH, BridgeEvent, EventsResponse
from agnostic_bridge._files import FileEvent, FileProvenanceResponse
from agnostic_bridge._workers import WORKERS_PATH, WorkersQueueConfig, WorkersResponse, WorkersScheduler

__all__ = [
    "BRIDGE_PREFIX",
    "EVENTS_PATH",
    "SCOPE_MAPPINGS",
    "WORKERS_PATH",
    "BridgeCapabilities",
    "BridgeEvalRun",
    "BridgeEvalRunInput",
    "BridgeEvent",
    "BridgeFeatures",
    "BridgeQueueFeatures",
    "EventsResponse",
    "FileEvent",
    "FileProvenanceResponse",
    "WorkersQueueConfig",
    "WorkersResponse",
    "WorkersScheduler",
    "__version__",
    "create_router",
    "install",
]
