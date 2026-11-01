"""agnostic-bridge: control-plane companion routes for an Agno AgentOS.

Install it on the AgentOS app and serve the app it returns::

    from agnostic_bridge import install

    agent_os = AgentOS(..., authorization=True)
    app = install(agent_os)  # instead of agent_os.get_app()

Routes live under ``/agnostic/v1``, are guarded by the same AgentOS auth layer as every built-in route, and need
the scopes in :data:`SCOPE_MAPPINGS` (``agent_os:admin`` passes too). The bridge stores nothing and never calls a
model.
"""

from agnostic_bridge._app import BRIDGE_PREFIX, SCOPE_MAPPINGS, create_router, install
from agnostic_bridge._capabilities import BridgeCapabilities, BridgeFeatures, BridgeQueueFeatures, __version__

__all__ = [
    "BRIDGE_PREFIX",
    "SCOPE_MAPPINGS",
    "BridgeCapabilities",
    "BridgeFeatures",
    "BridgeQueueFeatures",
    "__version__",
    "create_router",
    "install",
]
