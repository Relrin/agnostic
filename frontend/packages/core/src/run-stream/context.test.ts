import { describe, expect, it } from "vitest";

import { contextShares, contextWindow, declaredWindow, storedContext, usedTokens } from "./context";
import { initialRunState, reduceAll } from "./reducer";

describe("context windows", () => {
  it("knows the window of common models", () => {
    expect(contextWindow("claude-sonnet-4-6")).toBe(1_000_000);
    expect(contextWindow("claude-opus-5-5")).toBe(1_000_000);
    expect(contextWindow("claude-sonnet-4-5-20250929")).toBe(200_000);
    expect(contextWindow("gpt-4o-mini")).toBe(128_000);
    expect(contextWindow("gpt-4.1")).toBe(1_047_576);
    expect(contextWindow("openai/gpt-5")).toBe(400_000);
    expect(contextWindow("o3-mini")).toBe(200_000);
    expect(contextWindow("mock-1")).toBeUndefined();
    expect(contextWindow(undefined)).toBeUndefined();
  });

  it("lets a component declare its own window", () => {
    expect(declaredWindow({ context_window: 32_000 })).toBe(32_000);
    expect(declaredWindow({ context_window: "big" })).toBeUndefined();
  });
});

describe("context usage", () => {
  it("takes the latest root model request, not the run's summed totals", () => {
    const state = reduceAll(
      [
        { event: "RunStarted", run_id: "r1", model: "gpt-4o", event_index: 0 },
        {
          event: "ModelRequestCompleted",
          run_id: "r1",
          input_tokens: 1200,
          output_tokens: 40,
          event_index: 1,
        },
        {
          event: "ModelRequestCompleted",
          run_id: "r1",
          input_tokens: 1900,
          output_tokens: 300,
          event_index: 2,
        },
        {
          event: "RunCompleted",
          run_id: "r1",
          metrics: { input_tokens: 3100, output_tokens: 340 },
          event_index: 3,
        },
      ],
      initialRunState(),
    );
    expect(state.context).toMatchObject({ inputTokens: 1900, outputTokens: 300 });
    expect(state.unknownEvents).toBe(0);
  });

  it("adds cached input for providers that report it apart from input tokens", () => {
    const base = { outputTokens: 10, cacheReadTokens: 500, cacheWriteTokens: 100, reasoningTokens: 0 };
    expect(usedTokens({ ...base, inputTokens: 50, provider: "Anthropic" })).toBe(660);
    expect(usedTokens({ ...base, inputTokens: 650, provider: "OpenAI" })).toBe(660);
  });

  it("reads a stored run's last assistant message", () => {
    const usage = storedContext(
      [
        { role: "system", content: "Be brief." },
        { role: "user", content: "Hi" },
        { role: "assistant", content: "Hello", metrics: { input_tokens: 90, output_tokens: 5 } },
      ],
      { details: { model: [{ id: "gpt-4o", provider: "OpenAI" }] } },
    );
    expect(usage).toMatchObject({ inputTokens: 90, outputTokens: 5, model: "gpt-4o" });
  });

  it("splits the input by source and scales it to the measured total", () => {
    const usage = {
      inputTokens: 100,
      outputTokens: 20,
      cacheReadTokens: 0,
      cacheWriteTokens: 0,
      reasoningTokens: 0,
    };
    const shares = contextShares(usage, [
      { role: "system", content: "x".repeat(160) },
      { role: "user", content: "y".repeat(80) },
      { role: "tool", content: "z".repeat(40) },
      { role: "assistant", content: "w".repeat(80) },
    ]);
    const byKey = Object.fromEntries(shares.map((share) => [share.key, share.tokens]));
    expect(byKey).toEqual({ system: 40, conversation: 20, tools: 10, definitions: 30, output: 20 });
  });
});
