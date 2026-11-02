"""The Metrics page: daily aggregates, per-component usage and cost.

AgentOS ``/metrics`` rows give runs and sessions per component type, distinct users, token totals and per-model *run
counts* per day, but no per-component split and no tokens per model. Session list items carry both: the component
ids and ``metrics.details`` with tokens per model. Per-component rows therefore come from the sessions active in the
range; whatever the ``/metrics`` totals hold beyond what those sessions explain (older sessions, sessions without
model details, a capped sample) is the *gap*, priced across models by their share of runs and flagged approximate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, cast

from agnostic_observe.domain.costs import ModelKey, Price, Tokens, cost, find_price
from agnostic_observe.domain.overview import TraceRow, parse_time

type Kind = Literal["agent", "team", "workflow"]
KINDS: tuple[Kind, ...] = ("agent", "team", "workflow")


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def tokens_of(raw: Mapping[str, Any]) -> Tokens:
    """Token metrics as agno reports them (``input_tokens``, ``output_tokens``, ``cache_read_tokens``, …)."""
    return Tokens(
        input=_int(raw.get("input_tokens")),
        output=_int(raw.get("output_tokens")),
        cache_read=_int(raw.get("cache_read_tokens")),
        reasoning=_int(raw.get("reasoning_tokens")),
    )


@dataclass(frozen=True, slots=True)
class RunsByKind:
    agent: int = 0
    team: int = 0
    workflow: int = 0

    @property
    def total(self) -> int:
        return self.agent + self.team + self.workflow

    def __add__(self, other: RunsByKind) -> RunsByKind:
        return RunsByKind(self.agent + other.agent, self.team + other.team, self.workflow + other.workflow)


@dataclass(frozen=True, slots=True)
class DayRow:
    day: date
    runs: RunsByKind
    sessions: RunsByKind
    users: int
    tokens: Tokens
    model_runs: Mapping[ModelKey, int] = field(default_factory=dict[ModelKey, int])

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> DayRow | None:
        moment = parse_time(raw.get("date"))
        if moment is None:
            return None
        models: Counter[ModelKey] = Counter()
        for item in cast("list[Any]", raw.get("model_metrics") or []):
            entry = _dict(item)
            if not entry:
                continue
            model = str(entry.get("model_id") or entry.get("model") or "unknown")
            provider = entry.get("model_provider") or entry.get("provider") or None
            models[ModelKey(model, str(provider) if provider else None)] += _int(
                entry.get("count") or entry.get("runs")
            )
        return cls(
            day=moment.date(),
            runs=RunsByKind(*(_int(raw.get(f"{kind}_runs_count")) for kind in KINDS)),
            sessions=RunsByKind(*(_int(raw.get(f"{kind}_sessions_count")) for kind in KINDS)),
            users=_int(raw.get("users_count")),
            tokens=tokens_of(_dict(raw.get("token_metrics"))),
            model_runs=dict(models),
        )

    def __add__(self, other: DayRow) -> DayRow:
        models = Counter(self.model_runs)
        models.update(other.model_runs)
        return DayRow(
            self.day,
            self.runs + other.runs,
            self.sessions + other.sessions,
            self.users + other.users,
            self.tokens + other.tokens,
            dict(models),
        )


def day_rows(payload: object, first: date, last: date) -> list[DayRow]:
    """One row per day from ``first`` to ``last`` (missing days are zero; duplicate rows of a day are summed)."""
    body = _dict(payload)
    raw: object = body.get("metrics") if body else payload
    merged: dict[date, DayRow] = {}
    for item in cast("list[Any]", raw or []):
        row = DayRow.parse(_dict(item))
        if row is None or not first <= row.day <= last:
            continue
        merged[row.day] = merged[row.day] + row if row.day in merged else row
    days: list[DayRow] = []
    current = first
    while current <= last:
        days.append(merged.get(current) or DayRow(current, RunsByKind(), RunsByKind(), 0, Tokens()))
        current = date.fromordinal(current.toordinal() + 1)
    return days


@dataclass(frozen=True, slots=True)
class ModelRuns:
    model: ModelKey
    runs: int
    share: float


def model_usage(days: Iterable[DayRow]) -> list[ModelRuns]:
    totals: Counter[ModelKey] = Counter()
    for day in days:
        totals.update(day.model_runs)
    overall = sum(totals.values())
    return [
        ModelRuns(model, runs, runs / overall if overall else 0.0)
        for model, runs in sorted(totals.items(), key=lambda item: (-item[1], item[0].model_id))
        if runs
    ]


# ---------------------------------------------------------------- sessions → components


@dataclass(frozen=True, slots=True)
class SessionUsage:
    session_id: str
    kind: Kind | None
    component_id: str | None
    user_id: str | None
    active_at: datetime | None
    tokens: Tokens
    by_model: Mapping[ModelKey, Tokens]

    @property
    def unattributed(self) -> Tokens:
        attributed = sum(self.by_model.values(), Tokens())
        return self.tokens.minus(attributed)

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SessionUsage:
        kind: Kind | None = None
        component: str | None = None
        for key, name in (("workflow_id", "workflow"), ("team_id", "team"), ("agent_id", "agent")):
            if raw.get(key):
                kind, component = cast("Kind", name), str(raw[key])
                break
        session_type = str(raw.get("session_type") or "")
        if session_type in KINDS:
            kind = session_type
        metrics = _dict(raw.get("metrics") or _dict(raw.get("session_data")).get("session_metrics"))
        by_model: dict[ModelKey, Tokens] = {}
        for entries in _dict(metrics.get("details")).values():
            for item in cast("list[Any]", entries if isinstance(entries, list) else []):
                entry = _dict(item)
                model = entry.get("id") or entry.get("model_id")
                if not model:
                    continue
                provider = entry.get("provider") or None
                key = ModelKey(str(model), str(provider) if provider else None)
                by_model[key] = by_model.get(key, Tokens()) + tokens_of(entry)
        tokens = tokens_of(metrics)
        if tokens.total == 0 and _int(raw.get("total_tokens")):
            tokens = Tokens(input=_int(raw.get("total_tokens")))
        return cls(
            session_id=str(raw.get("session_id") or ""),
            kind=kind,
            component_id=component,
            user_id=cast("str | None", raw.get("user_id")) or None,
            active_at=parse_time(raw.get("updated_at")) or parse_time(raw.get("created_at")),
            tokens=tokens,
            by_model=by_model,
        )


@dataclass(frozen=True, slots=True)
class ComponentUsage:
    id: str
    kind: Kind
    sessions: int
    runs: int | None
    tokens: Tokens
    by_model: Mapping[ModelKey, Tokens]
    unattributed: Tokens

    @property
    def models(self) -> list[tuple[ModelKey, Tokens]]:
        """Most tokens first."""
        return sorted(self.by_model.items(), key=lambda item: (-item[1].total, item[0].model_id))

    @property
    def primary_model(self) -> ModelKey | None:
        models = self.models
        return models[0][0] if models else None

    @property
    def extra_models(self) -> int:
        return max(len(self.by_model) - 1, 0)

    @property
    def approximate(self) -> bool:
        """Some tokens couldn't be tied to a model, and the component used several (priced at the primary's rate)."""
        return self.unattributed.total > 0 and len(self.by_model) > 1


def components(sessions: Iterable[SessionUsage], traces: Sequence[TraceRow] | None) -> list[ComponentUsage]:
    grouped: dict[tuple[Kind, str], list[SessionUsage]] = {}
    for session in sessions:
        if session.kind and session.component_id:
            grouped.setdefault((session.kind, session.component_id), []).append(session)
    runs: Counter[str] | None = None
    if traces is not None:
        runs = Counter(trace.component_id for trace in traces if trace.component_id)
    found: list[ComponentUsage] = []
    for (kind, component_id), items in grouped.items():
        by_model: dict[ModelKey, Tokens] = {}
        for item in items:
            for key, tokens in item.by_model.items():
                by_model[key] = by_model.get(key, Tokens()) + tokens
        found.append(
            ComponentUsage(
                id=component_id,
                kind=kind,
                sessions=len(items),
                runs=runs.get(component_id, 0) if runs is not None else None,
                tokens=sum((item.tokens for item in items), Tokens()),
                by_model=by_model,
                unattributed=sum((item.unattributed for item in items), Tokens()),
            )
        )
    found.sort(key=lambda item: (-(item.runs or 0), -item.tokens.total, item.id))
    return found


# ---------------------------------------------------------------- totals and cost


@dataclass(frozen=True, slots=True)
class Totals:
    runs: RunsByKind
    sessions: int
    active_users: int | None
    tokens: Tokens

    @property
    def runs_per_session(self) -> float | None:
        return self.runs.total / self.sessions if self.sessions else None


def totals(days: Sequence[DayRow], sessions: Sequence[SessionUsage] | None) -> Totals:
    """Active users: distinct ``user_id`` of the range's sessions, else the busiest day's count (a lower bound)."""
    users: int | None
    if sessions is not None:
        users = len({session.user_id for session in sessions if session.user_id})
    else:
        users = max((day.users for day in days), default=0) if days else None
    return Totals(
        runs=sum((day.runs for day in days), RunsByKind()),
        sessions=sum(day.sessions.total for day in days),
        active_users=users,
        tokens=sum((day.tokens for day in days), Tokens()),
    )


@dataclass(frozen=True, slots=True)
class ComponentCost:
    component_id: str
    amount: float
    approximate: bool


@dataclass(frozen=True, slots=True)
class SummaryCost:
    total: float
    approximate: bool
    components: Sequence[ComponentCost]
    gap: float
    unpriced: Sequence[ModelKey]


def _split(tokens: Tokens, shares: Sequence[ModelRuns]) -> list[tuple[ModelKey, Tokens]]:
    return [(share.model, tokens.scaled(share.share)) for share in shares if share.share > 0]


def summary_cost(
    items: Sequence[ComponentUsage], gap: Tokens, shares: Sequence[ModelRuns], prices: Sequence[Price]
) -> SummaryCost:
    """Per-component cost from tokens per model, plus the gap split by model run share.

    Tokens a component's sessions didn't tie to a model are priced at its primary model (split by run share when it
    has none).
    """
    unpriced: set[ModelKey] = set()

    def priced(parts: Iterable[tuple[ModelKey, Tokens]]) -> float:
        amount = 0.0
        for key, tokens in parts:
            if tokens.total == 0:
                continue
            price = find_price(key.model_id, key.provider, prices)
            if price is None:
                unpriced.add(key)
                continue
            amount += cost(tokens, price)
        return amount

    rows: list[ComponentCost] = []
    for item in items:
        parts = list(item.by_model.items())
        if item.unattributed.total:
            primary = item.primary_model
            parts.extend([(primary, item.unattributed)] if primary else _split(item.unattributed, shares))
        rows.append(ComponentCost(item.id, priced(parts), item.approximate))
    gap_cost = priced(_split(gap, shares))
    approximate = gap.total > 0 or any(row.approximate for row in rows)
    return SummaryCost(
        total=sum(row.amount for row in rows) + gap_cost,
        approximate=approximate,
        components=rows,
        gap=gap_cost,
        unpriced=sorted(unpriced, key=lambda key: (key.model_id, key.provider or "")),
    )
