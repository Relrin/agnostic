"""Request and response bodies of the artefacts routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agnostic_artifacts.domain.shares import Share


class ShareIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=255)
    storage_key: str = Field(min_length=1, max_length=1024)
    filename: str = Field(min_length=1, max_length=255)
    audience: Literal["org", "link"] = "org"
    ttl_seconds: int = Field(default=86_400, ge=300, description="How long the link works, in seconds")


class ShareOut(BaseModel):
    id: str
    instance_id: str
    session_id: str
    storage_key: str
    filename: str
    content_type: str
    size: int
    audience: Literal["org", "link"]
    state: Literal["active", "expired", "revoked"]
    created_by: str
    created_by_name: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    opened_count: int
    last_opened_at: datetime | None

    @classmethod
    def of(cls, share: Share, now: datetime) -> ShareOut:
        return cls(
            id=share.id,
            instance_id=share.instance_id,
            session_id=share.session_id,
            storage_key=share.storage_key,
            filename=share.filename,
            content_type=share.content_type,
            size=share.size,
            audience=share.audience,
            state=share.state(now),
            created_by=share.created_by,
            created_by_name=share.created_by_name,
            created_at=share.created_at,
            expires_at=share.expires_at,
            revoked_at=share.revoked_at,
            opened_count=share.opened_count,
            last_opened_at=share.last_opened_at,
        )


class CreatedShareOut(BaseModel):
    share: ShareOut
    token: str = Field(description="Shown once: the link is /s/{token}; only its hash is stored")
    path: str = Field(description="The web app path of the link")


class SharesOut(BaseModel):
    data: list[ShareOut]
    public_links: bool = Field(description="Whether 'anyone with the link' shares are allowed here")


class SharedArtifactOut(BaseModel):
    """What a link shows before its bytes: enough to pick the viewer."""

    filename: str
    content_type: str
    size: int
    audience: Literal["org", "link"]
    shared_by: str
    created_at: datetime
    expires_at: datetime
