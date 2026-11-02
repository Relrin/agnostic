// Cost estimates from token counts and the price table, recomputed in the browser as people edit prices. Mirrors
// the backend arithmetic (agnostic_observe.domain.costs / metrics.summary_cost): cache reads are part of input tokens
// and billed at the cache-read rate when one is set, reasoning tokens are part of output tokens and billed at the
// reasoning rate when one is set. Prices are USD per one million tokens.
import type { MetricsSummaryOut, PriceIn, TokensOut } from "@agnostic/api";

export type Price = Pick<
  PriceIn,
  "model_id" | "provider" | "input_per_1m" | "output_per_1m" | "cache_read_per_1m" | "reasoning_per_1m"
>;
export type TokenCounts = Pick<TokensOut, "input" | "output" | "cache_read" | "reasoning">;

const PER_TOKENS = 1_000_000;

export function tokenCost(tokens: TokenCounts, price: Price): number {
  const cacheRead = Math.min(tokens.cache_read, tokens.input);
  const reasoning = Math.min(tokens.reasoning, tokens.output);
  const cacheRate = price.cache_read_per_1m ?? price.input_per_1m;
  const reasoningRate = price.reasoning_per_1m ?? price.output_per_1m;
  return (
    ((tokens.input - cacheRead) * price.input_per_1m +
      cacheRead * cacheRate +
      (tokens.output - reasoning) * price.output_per_1m +
      reasoning * reasoningRate) /
    PER_TOKENS
  );
}

/** Exact model id (case-insensitive); a row for the same provider wins over a provider-less row. */
export function findPrice(
  modelId: string,
  provider: string | null | undefined,
  prices: readonly Price[],
): Price | undefined {
  const candidates = prices.filter((price) => price.model_id.toLowerCase() === modelId.toLowerCase());
  if (provider) {
    const exact = candidates.find((price) => price.provider?.toLowerCase() === provider.toLowerCase());
    if (exact) return exact;
  }
  return candidates.find((price) => !price.provider) ?? candidates[0];
}

function scaled(tokens: TokenCounts, factor: number): TokenCounts {
  return {
    input: Math.round(tokens.input * factor),
    output: Math.round(tokens.output * factor),
    cache_read: Math.round(tokens.cache_read * factor),
    reasoning: Math.round(tokens.reasoning * factor),
  };
}

type Part = { model: string; provider: string | null | undefined; tokens: TokenCounts };

export type CostBreakdown = {
  total: number;
  byComponent: Record<string, number>;
  gap: number;
  approximate: boolean;
  unpriced: string[];
};

/** The page's cost numbers for the current price table (same rules as the server's estimate). */
export function summaryCost(summary: MetricsSummaryOut, prices: readonly Price[]): CostBreakdown {
  const unpriced = new Set<string>();
  const shares = summary.model_usage.filter((model) => model.share > 0);
  const split = (tokens: TokenCounts): Part[] =>
    shares.map((model) => ({
      model: model.model_id,
      provider: model.provider,
      tokens: scaled(tokens, model.share),
    }));
  const priced = (parts: readonly Part[]): number =>
    parts.reduce((sum, part) => {
      if (part.tokens.input + part.tokens.output === 0) return sum;
      const price = findPrice(part.model, part.provider, prices);
      // A row still at zero is a model listed for entry, not a free one.
      if (!price || (price.input_per_1m === 0 && price.output_per_1m === 0)) {
        unpriced.add(part.model);
        return sum;
      }
      return sum + tokenCost(part.tokens, price);
    }, 0);

  const byComponent: Record<string, number> = {};
  for (const component of summary.components) {
    const parts: Part[] = component.models.map((model) => ({
      model: model.model_id,
      provider: model.provider,
      tokens: model.tokens,
    }));
    const unattributed = component.unattributed;
    if (unattributed.input + unattributed.output > 0) {
      const primary = component.models[0];
      parts.push(
        ...(primary
          ? [{ model: primary.model_id, provider: primary.provider, tokens: unattributed }]
          : split(unattributed)),
      );
    }
    byComponent[component.id] = priced(parts);
  }
  const gap = priced(split(summary.gap_tokens));
  const total = Object.values(byComponent).reduce((sum, value) => sum + value, 0) + gap;
  const approximate =
    summary.gap_tokens.input + summary.gap_tokens.output > 0 ||
    summary.components.some((component) => component.approximate);
  return { total, byComponent, gap, approximate, unpriced: [...unpriced].sort() };
}

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

/** 111.348 → "$111.35"; tiny amounts keep two significant digits ("$0.0042"). */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value > 0 && value < 0.01) return `$${value.toPrecision(2)}`;
  return USD.format(value);
}

/** 17_900_000 → "17.9 M", 310_000 → "0.3 M" (Metrics shows tokens in millions). */
export function formatMillions(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value / 1_000_000).toFixed(digits)} M`;
}
