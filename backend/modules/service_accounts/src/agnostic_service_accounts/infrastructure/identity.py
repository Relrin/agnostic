"""Step-up for privileged grants, through identity's recent-authentication check."""

from __future__ import annotations

from agnostic_identity.facade import IdentityFacade
from agnostic_kernel.auth import Principal


class IdentityRecentAuthentication:
    """``IdentityFacade.require_recent_auth``: a 403 ``reauth_required`` until the person steps up."""

    def __init__(self, identity: IdentityFacade) -> None:
        self._identity = identity

    async def require(self, principal: Principal) -> None:
        await self._identity.require_recent_auth(principal)
