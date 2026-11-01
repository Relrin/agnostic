"""Response bodies of ``/api/v1/search``."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agnostic_search.application.ports import Hit


class SearchHitOut(BaseModel):
    kind: str = Field(description="member, instance, agent, team, workflow, …")
    ref: str
    instance_id: str | None
    title: str
    subtitle: str
    url_path: str
    score: float

    @classmethod
    def from_hit(cls, hit: Hit) -> SearchHitOut:
        return cls(
            kind=hit.kind,
            ref=hit.ref,
            instance_id=hit.instance_id,
            title=hit.title,
            subtitle=hit.body[:160],
            url_path=hit.url_path,
            score=round(hit.score, 4),
        )


class SearchOut(BaseModel):
    data: list[SearchHitOut]
