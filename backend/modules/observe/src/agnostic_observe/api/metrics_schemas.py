"""Request and response bodies of the Metrics page endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from agnostic_observe.application.metrics import MetricsSummary
from agnostic_observe.application.ports import PriceEntry
from agnostic_observe.domain.costs import ModelKey, Price, Tokens
from agnostic_observe.domain.metrics import RunsByKind


class TokensOut(BaseModel):
    input: int = Field(description="Input tokens, cache reads included")
    output: int = Field(description="Output tokens, reasoning included")
    cache_read: int
    reasoning: int
    total: int

    @classmethod
    def of(cls, tokens: Tokens) -> TokensOut:
        return cls(
            input=tokens.input,
            output=tokens.output,
            cache_read=tokens.cache_read,
            reasoning=tokens.reasoning,
            total=tokens.total,
        )


class RunsOut(BaseModel):
    agent: int
    team: int
    workflow: int
    total: int

    @classmethod
    def of(cls, runs: RunsByKind) -> RunsOut:
        return cls(agent=runs.agent, team=runs.team, workflow=runs.workflow, total=runs.total)


class DayOut(BaseModel):
    date: date
    runs: RunsOut
    tokens: TokensOut


class TotalsOut(BaseModel):
    runs: RunsOut
    sessions: int
    runs_per_session: float | None
    active_users: int | None
    tokens: TokensOut


class ModelUsageOut(BaseModel):
    model_id: str
    provider: str | None
    runs: int
    share: float


class ModelTokensOut(BaseModel):
    model_id: str
    provider: str | None
    tokens: TokensOut


class ComponentOut(BaseModel):
    id: str
    type: Literal["agent", "team", "workflow"]
    sessions: int
    runs: int | None = Field(description="From traces; null when traces aren't readable")
    tokens: TokensOut
    models: list[ModelTokensOut] = Field(description="Most tokens first; the first is the primary model")
    unattributed: TokensOut = Field(description="Tokens the sessions didn't tie to a model")
    extra_models: int
    estimated_cost: float
    approximate: bool


class PriceIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=100)
    input_per_1m: float = Field(ge=0)
    output_per_1m: float = Field(ge=0)
    cache_read_per_1m: float | None = Field(default=None, ge=0)
    reasoning_per_1m: float | None = Field(default=None, ge=0)

    def to_domain(self) -> Price:
        return Price(
            model_id=self.model_id.strip(),
            provider=(self.provider or "").strip() or None,
            input_per_1m=self.input_per_1m,
            output_per_1m=self.output_per_1m,
            cache_read_per_1m=self.cache_read_per_1m,
            reasoning_per_1m=self.reasoning_per_1m,
        )


class PriceTableIn(BaseModel):
    prices: list[PriceIn] = Field(max_length=500)


class PriceOut(PriceIn):
    currency: Literal["USD"] = "USD"
    source: Literal["org", "instance"]
    updated_at: datetime | None
    updated_by: str | None

    @classmethod
    def of(cls, entry: PriceEntry) -> PriceOut:
        price = entry.price
        return cls(
            model_id=price.model_id,
            provider=price.provider,
            input_per_1m=price.input_per_1m,
            output_per_1m=price.output_per_1m,
            cache_read_per_1m=price.cache_read_per_1m,
            reasoning_per_1m=price.reasoning_per_1m,
            source=entry.scope,
            updated_at=entry.updated_at,
            updated_by=entry.updated_by,
        )


class PriceTableOut(BaseModel):
    prices: list[PriceOut]


class CostOut(BaseModel):
    currency: Literal["USD"] = "USD"
    total: float
    approximate: bool
    gap: float = Field(description="Part of the total priced by model run share")
    unpriced_models: list[str]


class MetricsSummaryOut(BaseModel):
    instance_id: str
    start: date
    end: date
    generated_at: datetime
    last_aggregated_at: datetime | None = Field(description="When AgentOS last recomputed its daily aggregates")
    totals: TotalsOut
    days: list[DayOut]
    model_usage: list[ModelUsageOut]
    components: list[ComponentOut]
    gap_tokens: TokensOut = Field(description="Daily-total tokens that the range's sessions don't explain")
    prices: list[PriceOut]
    cost: CostOut
    sampled: bool
    unavailable: dict[str, str]

    @classmethod
    def of(cls, summary: MetricsSummary) -> MetricsSummaryOut:
        costs = {row.component_id: row for row in summary.cost.components}
        totals = summary.totals
        return cls(
            instance_id=summary.instance_id,
            start=summary.first,
            end=summary.last,
            generated_at=summary.generated_at,
            last_aggregated_at=summary.last_aggregated_at,
            totals=TotalsOut(
                runs=RunsOut.of(totals.runs),
                sessions=totals.sessions,
                runs_per_session=totals.runs_per_session,
                active_users=totals.active_users,
                tokens=TokensOut.of(totals.tokens),
            ),
            days=[
                DayOut(date=day.day, runs=RunsOut.of(day.runs), tokens=TokensOut.of(day.tokens)) for day in summary.days
            ],
            model_usage=[
                ModelUsageOut(
                    model_id=item.model.model_id, provider=item.model.provider, runs=item.runs, share=item.share
                )
                for item in summary.model_usage
            ],
            components=[
                ComponentOut(
                    id=item.id,
                    type=item.kind,
                    sessions=item.sessions,
                    runs=item.runs,
                    tokens=TokensOut.of(item.tokens),
                    models=[_model_tokens(key, tokens) for key, tokens in item.models],
                    unattributed=TokensOut.of(item.unattributed),
                    extra_models=item.extra_models,
                    estimated_cost=costs[item.id].amount if item.id in costs else 0.0,
                    approximate=item.approximate,
                )
                for item in summary.components
            ],
            gap_tokens=TokensOut.of(summary.gap),
            prices=[PriceOut.of(entry) for entry in summary.prices],
            cost=CostOut(
                total=summary.cost.total,
                approximate=summary.cost.approximate,
                gap=summary.cost.gap,
                unpriced_models=[key.model_id for key in summary.cost.unpriced],
            ),
            sampled=summary.sampled,
            unavailable=summary.unavailable,
        )


def _model_tokens(key: ModelKey, tokens: Tokens) -> ModelTokensOut:
    return ModelTokensOut(model_id=key.model_id, provider=key.provider, tokens=TokensOut.of(tokens))
