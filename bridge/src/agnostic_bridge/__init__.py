"""agnostic-bridge: control-plane companion routes for an Agno AgentOS.

Install it on the AgentOS app and serve the app it returns::

    from agnostic_bridge import install

    agent_os = AgentOS(..., authorization=True)
    app = install(agent_os)  # instead of agent_os.get_app()

Routes live under ``/agnostic/v1``, are guarded by the same AgentOS auth layer as every built-in route, and need
the scopes in :data:`SCOPE_MAPPINGS` (``agent_os:admin`` passes too). The bridge keeps no state of its own; its
eval route runs AgentOS's own eval helpers, which call models and store the result in the AgentOS db; its file
provenance route reads the traces AgentOS already stores; its workers route describes the replica that answers; its
events route reads the approvals and schedule runs AgentOS already stores; its component routes rebuild configs with
agno's ``from_dict`` without storing them; its introspection routes read code-defined components and registry entries;
its CEL route evaluates a workflow expression with agno's own CEL evaluation. With the tool catalog on, it
pulls the control plane's approved MCP servers and toolkits and keeps them in the AgentOS registry while
the process runs; its tool catalog routes report and refresh what it built. Its artefact routes list the run media
AgentOS stores; ``agnostic_bridge.artifacts`` collects the files agents produce into that media.
"""

from agnostic_bridge._app import BRIDGE_PREFIX, SCOPE_MAPPINGS, create_router, install
from agnostic_bridge._artifacts import (
    ARTIFACTS_PATH,
    RECENT_ARTIFACTS_PATH,
    SYNC_ARTIFACTS_PATH,
    Artifact,
    ArtifactList,
    SyncResult,
)
from agnostic_bridge._capabilities import (
    BridgeCapabilities,
    BridgeFeatures,
    BridgeQueueFeatures,
    BridgeToolCatalogFeatures,
    __version__,
)
from agnostic_bridge._catalog import CatalogStatus, ToolCatalogConfig, ToolCatalogSync
from agnostic_bridge._cel import EVALUATE_CEL_PATH, CelEvaluation, CelEvaluationError, CelEvaluationInput
from agnostic_bridge._components import (
    NORMALIZE_PATH,
    VALIDATE_PATH,
    ComponentConfigInput,
    ComponentError,
    NormalizedConfig,
    ValidationResult,
)
from agnostic_bridge._direct import direct_mode_cors
from agnostic_bridge._evals import BridgeEvalRun, BridgeEvalRunInput
from agnostic_bridge._events import EVENTS_PATH, BridgeEvent, EventsResponse
from agnostic_bridge._files import FileEvent, FileProvenanceResponse
from agnostic_bridge._introspect import INTROSPECT_COMPONENTS_PATH, REGISTRY_SOURCE_PATH, CodeComponent, RegistrySource
from agnostic_bridge._workers import WORKERS_PATH, WorkersQueueConfig, WorkersResponse, WorkersScheduler

__all__ = [
    "ARTIFACTS_PATH",
    "BRIDGE_PREFIX",
    "EVALUATE_CEL_PATH",
    "EVENTS_PATH",
    "INTROSPECT_COMPONENTS_PATH",
    "NORMALIZE_PATH",
    "RECENT_ARTIFACTS_PATH",
    "REGISTRY_SOURCE_PATH",
    "SCOPE_MAPPINGS",
    "SYNC_ARTIFACTS_PATH",
    "VALIDATE_PATH",
    "WORKERS_PATH",
    "Artifact",
    "ArtifactList",
    "BridgeCapabilities",
    "BridgeEvalRun",
    "BridgeEvalRunInput",
    "BridgeEvent",
    "BridgeFeatures",
    "BridgeQueueFeatures",
    "BridgeToolCatalogFeatures",
    "CatalogStatus",
    "CelEvaluation",
    "CelEvaluationError",
    "CelEvaluationInput",
    "CodeComponent",
    "ComponentConfigInput",
    "ComponentError",
    "EventsResponse",
    "FileEvent",
    "FileProvenanceResponse",
    "NormalizedConfig",
    "RegistrySource",
    "SyncResult",
    "ToolCatalogConfig",
    "ToolCatalogSync",
    "ValidationResult",
    "WorkersQueueConfig",
    "WorkersResponse",
    "WorkersScheduler",
    "__version__",
    "create_router",
    "direct_mode_cors",
    "install",
]
