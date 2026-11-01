"""Command-palette documents: org members (name and email, for ⌘K "people")."""

from __future__ import annotations

from collections.abc import Sequence

from dishka import AsyncContainer

from agnostic_identity.facade import IdentityFacade
from agnostic_kernel.modules import SearchDocument
from agnostic_org.facade import OrgFacade


async def member_documents(container: AsyncContainer) -> Sequence[SearchDocument]:
    members = [member for member in await (await container.get(OrgFacade)).members() if member.active]
    users = {
        user.id: user for user in await (await container.get(IdentityFacade)).get_users([m.user_id for m in members])
    }
    documents: list[SearchDocument] = []
    for member in members:
        user = users.get(member.user_id)
        if user is None:
            continue
        documents.append(
            SearchDocument(
                kind="member",
                ref=member.user_id,
                title=user.display_name,
                body=f"{user.email} {member.org_role.value}",
                url_path=f"/access/people?member={member.user_id}",
                required_scope="org:members:read",
            )
        )
    return documents
