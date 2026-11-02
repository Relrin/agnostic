import type { MetricsSummaryOut } from "@agnostic/api";
import { describe, expect, it } from "vitest";

import { findPrice, formatMillions, formatUsd, summaryCost, tokenCost, type Price } from "./costs";

const OPUS: Price = {
  model_id: "claude-opus-5-5",
  provider: "anthropic",
  input_per_1m: 5,
  output_per_1m: 25,
};
const HAIKU: Price = {
  model_id: "claude-haiku-5-5",
  provider: null,
  input_per_1m: 1,
  output_per_1m: 5,
  cache_read_per_1m: 0.1,
  reasoning_per_1m: 8,
};
const tokens = (input: number, output: number, cache_read = 0, reasoning = 0) => ({
  input,
  output,
  cache_read,
  reasoning,
  total: input + output,
});

describe("cost math (same cases as the backend tests)", () => {
  it("bills cache reads and reasoning at their own rates when set", () => {
    const usage = tokens(1_000_000, 200_000, 400_000, 50_000);
    expect(tokenCost(usage, OPUS)).toBeCloseTo(5 + (200_000 * 25) / 1e6);
    expect(tokenCost(usage, HAIKU)).toBeCloseTo(
      (600_000 * 1 + 400_000 * 0.1 + 150_000 * 5 + 50_000 * 8) / 1e6,
    );
  });

  it("prefers the provider's row", () => {
    const prices: Price[] = [
      { model_id: "gpt-6.1-sol", provider: null, input_per_1m: 2.5, output_per_1m: 10 },
      { model_id: "gpt-6.1-sol", provider: "openai", input_per_1m: 2, output_per_1m: 8 },
    ];
    expect(findPrice("GPT-6.1-SOL", "openai", prices)).toBe(prices[1]);
    expect(findPrice("gpt-6.1-sol", "azure", prices)).toBe(prices[0]);
    expect(findPrice("unknown", null, prices)).toBeUndefined();
  });

  it("prices components, unattributed tokens and the gap like the server", () => {
    const summary = {
      components: [
        {
          id: "ticket-router",
          type: "workflow",
          sessions: 1,
          runs: 3,
          tokens: tokens(1_300, 100),
          models: [
            { model_id: "claude-haiku-5-5", provider: null, tokens: tokens(1_000_000, 0) },
            { model_id: "gpt", provider: null, tokens: tokens(0, 100) },
          ],
          unattributed: tokens(1_000_000, 0),
          extra_models: 1,
          estimated_cost: 0,
          approximate: true,
        },
      ],
      gap_tokens: tokens(4_000_000, 0),
      model_usage: [
        { model_id: "claude-haiku-5-5", provider: null, runs: 3, share: 0.75 },
        { model_id: "gpt", provider: null, runs: 1, share: 0.25 },
      ],
    } as unknown as MetricsSummaryOut;
    const prices: Price[] = [
      { model_id: "claude-haiku-5-5", provider: null, input_per_1m: 1, output_per_1m: 5 },
      { model_id: "gpt", provider: null, input_per_1m: 2, output_per_1m: 10 },
    ];
    const result = summaryCost(summary, prices);
    expect(result.byComponent["ticket-router"]).toBeCloseTo(1 + (100 * 10) / 1e6 + 1);
    expect(result.gap).toBeCloseTo(3 + 2);
    expect(result.total).toBeCloseTo((result.byComponent["ticket-router"] ?? 0) + result.gap);
    expect(result.approximate).toBe(true);
    expect(summaryCost(summary, prices.slice(0, 1)).unpriced).toEqual(["gpt"]);
  });

  it("formats money and millions", () => {
    expect(formatUsd(111.348)).toBe("$111.35");
    expect(formatUsd(0.0042)).toBe("$0.0042");
    expect(formatUsd(undefined)).toBe("—");
    expect(formatMillions(17_900_000)).toBe("17.9 M");
  });
});
