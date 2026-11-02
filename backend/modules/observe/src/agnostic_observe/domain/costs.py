"""Cost estimates from token counts and the customer's price table.

Token semantics follow agno's metrics: cache-read tokens are part of the input tokens and reasoning tokens are part
of the output tokens. Cache reads are billed at the cache-read rate when the price row has one (otherwise at the
input rate); reasoning tokens at the reasoning rate when set (otherwise at the output rate). Prices are per one
million tokens. The frontend mirrors this arithmetic for live recomputation, so keep the two in step.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

PER_TOKENS = 1_000_000


@dataclass(frozen=True, slots=True)
class Tokens:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    """Included in ``input``."""
    reasoning: int = 0
    """Included in ``output``."""

    @property
    def total(self) -> int:
        return self.input + self.output

    def __add__(self, other: Tokens) -> Tokens:
        return Tokens(
            self.input + other.input,
            self.output + other.output,
            self.cache_read + other.cache_read,
            self.reasoning + other.reasoning,
        )

    def scaled(self, factor: float) -> Tokens:
        return Tokens(
            round(self.input * factor),
            round(self.output * factor),
            round(self.cache_read * factor),
            round(self.reasoning * factor),
        )

    def minus(self, other: Tokens) -> Tokens:
        """What ``self`` has beyond ``other`` (never negative)."""
        return Tokens(
            max(self.input - other.input, 0),
            max(self.output - other.output, 0),
            max(self.cache_read - other.cache_read, 0),
            max(self.reasoning - other.reasoning, 0),
        )


@dataclass(frozen=True, slots=True)
class Price:
    model_id: str
    provider: str | None
    input_per_1m: float
    output_per_1m: float
    cache_read_per_1m: float | None = None
    reasoning_per_1m: float | None = None
    currency: str = "USD"


def cost(tokens: Tokens, price: Price) -> float:
    cache_read = min(tokens.cache_read, tokens.input)
    reasoning = min(tokens.reasoning, tokens.output)
    cache_rate = price.cache_read_per_1m if price.cache_read_per_1m is not None else price.input_per_1m
    reasoning_rate = price.reasoning_per_1m if price.reasoning_per_1m is not None else price.output_per_1m
    amount = (
        (tokens.input - cache_read) * price.input_per_1m
        + cache_read * cache_rate
        + (tokens.output - reasoning) * price.output_per_1m
        + reasoning * reasoning_rate
    )
    return amount / PER_TOKENS


def find_price(model_id: str, provider: str | None, prices: Iterable[Price]) -> Price | None:
    """Exact model id (case-insensitive); a row for the same provider wins over a provider-less row."""
    candidates = [price for price in prices if price.model_id.lower() == model_id.lower()]
    if provider:
        for price in candidates:
            if price.provider and price.provider.lower() == provider.lower():
                return price
    return next((price for price in candidates if not price.provider), candidates[0] if candidates else None)


@dataclass(frozen=True, slots=True)
class ModelKey:
    model_id: str
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class Estimate:
    total: float
    by_model: Mapping[ModelKey, float] = field(default_factory=dict[ModelKey, float])
    unpriced: Sequence[ModelKey] = ()
    """Models with tokens but no price row: left out of ``total``."""


def estimate(usage: Mapping[ModelKey, Tokens], prices: Sequence[Price]) -> Estimate:
    by_model: dict[ModelKey, float] = {}
    unpriced: list[ModelKey] = []
    for key, tokens in usage.items():
        if tokens.total == 0:
            continue
        price = find_price(key.model_id, key.provider, prices)
        if price is None:
            unpriced.append(key)
            continue
        by_model[key] = cost(tokens, price)
    return Estimate(total=sum(by_model.values()), by_model=by_model, unpriced=unpriced)


def merged_prices(org: Sequence[Price], instance: Sequence[Price]) -> list[Price]:
    """The effective table: instance rows override org rows for the same (model, provider)."""
    keys = {(price.model_id.lower(), (price.provider or "").lower()) for price in instance}
    kept = [price for price in org if (price.model_id.lower(), (price.provider or "").lower()) not in keys]
    return sorted([*kept, *instance], key=lambda price: (price.model_id.lower(), price.provider or ""))
