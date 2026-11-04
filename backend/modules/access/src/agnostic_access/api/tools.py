"""Assistant tool: why someone can or can't do something, the structured "Check a permission" call."""

from __future__ import annotations

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_access.application.use_cases import Explain, structured_scope
from agnostic_identity.facade import IdentityFacade
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec


class ExplainArgs(BaseModel):
    person: str = Field("me", description='"me", a user id (usr_…) or an email address')
    resource: str = Field(description="agents, teams, workflows, sessions, traces, memories, approvals, schedules, …")
    verb: str = Field(description="read, run, write, delete, publish, …")
    component: str | None = Field(None, description="Agent, team or workflow id, for per-component scopes")
    other_instance: str | None = Field(None, description="Ask about another instance (slug) instead of this one")


async def explain_permission(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, ExplainArgs)
    user_id = call.principal.id
    if args.person.strip().lower() not in {"me", "i", "myself", call.principal.id}:
        identity = await container.get(IdentityFacade)
        wanted = args.person.strip()
        user = await identity.find_user_by_email(wanted) if "@" in wanted else await identity.get_user(wanted)
        if user is None:
            raise NotFoundError(f"There is no person {wanted!r}; use their email address or user id.")
        user_id = user.id
    scope = structured_scope(args.resource, args.verb, args.component)
    explanation = await (await container.get(Explain))(
        call.principal,
        user_id=user_id,
        scope=scope,
        instance_ref=args.other_instance or call.instance_id,
        action=None,
    )
    return ToolResult(
        {
            "person": user_id,
            "scope": explanation.scope,
            "allowed": explanation.allowed,
            "explanation": explanation.text,
            "granted_by": [
                {
                    "role": grant.role_name,
                    "via_group": grant.via_group_name,
                    "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                }
                for grant in explanation.granted_by
            ],
            "missing_scopes": list(explanation.missing_scopes),
            "alternatives": [alternative.label for alternative in explanation.alternatives],
        },
        [Source("people", "People & groups", "/access/people")],
    )


TOOLS = (
    ToolSpec(
        "explain_permission",
        "Whether a person can do something on an instance, which role grants it, and what would grant it if not. "
        "Explaining someone else needs org:roles:read.",
        explain_permission,
        ExplainArgs,
    ),
)
