// How much of the model's context window a conversation fills: the latest model request's token counts measured
// against the model's window, with an estimated split by where the tokens came from.
import type { ContextUsage } from "./reducer";

/** Known context windows, matched against the model id in order (first match wins). */
const WINDOWS: readonly [RegExp, number][] = [
  // Anthropic: the 4.6+ Opus and Sonnet models, every 5.x model and Haiku 5.5 hold 1M tokens; older ones 200k.
  [/claude-(opus|sonnet)-4-[6-9]/, 1_000_000],
  [/claude-(fable|mythos|opus|sonnet|haiku)-5/, 1_000_000],
  [/claude/, 200_000],
  // OpenAI
  [/gpt-4\.1/, 1_047_576],
  [/gpt-5/, 400_000],
  [/^(o1|o3|o4)(-|$)/, 200_000],
  [/gpt-4o|gpt-4-turbo|gpt-oss/, 128_000],
  [/gpt-4/, 8_192],
  [/gpt-3\.5/, 16_385],
  // Google
  [/gemini-(1\.5|2|3)/, 1_048_576],
  [/gemma/, 128_000],
  // Others
  [/grok-4/, 256_000],
  [/grok/, 131_072],
  [/mistral-large|mistral-medium|codestral|ministral/, 128_000],
  [/deepseek/, 128_000],
  [/llama-?(3\.[1-3]|4)/, 128_000],
  [/qwen/, 131_072],
  [/kimi|moonshot/, 256_000],
  [/command-r|command-a/, 128_000],
];

/** The context window of a model (by id), or `undefined` when it is not one we know. */
export function contextWindow(model: string | undefined): number | undefined {
  if (!model) return undefined;
  const id = model.toLowerCase().split("/").at(-1) ?? "";
  return WINDOWS.find(([pattern]) => pattern.test(id))?.[1];
}

/** A window the component declares for itself (`metadata.context_window`), which wins over the known list. */
export function declaredWindow(metadata: Record<string, unknown> | undefined): number | undefined {
  const value = metadata?.context_window;
  return typeof value === "number" && value > 0 ? value : undefined;
}

/** Providers that report cached input separately from `input_tokens` (the others include it). */
function cacheIsSeparate(usage: ContextUsage): boolean {
  return /anthropic|claude/i.test(`${usage.provider ?? ""} ${usage.model ?? ""}`);
}

/** Tokens the conversation occupies after the latest request: everything sent plus what the model wrote. */
export function usedTokens(usage: ContextUsage): number {
  const cached = cacheIsSeparate(usage) ? usage.cacheReadTokens + usage.cacheWriteTokens : 0;
  return usage.inputTokens + cached + usage.outputTokens;
}

/** Input tokens of the latest request, including cached ones whatever the provider's convention. */
export function inputTokens(usage: ContextUsage): number {
  return usage.inputTokens + (cacheIsSeparate(usage) ? usage.cacheReadTokens + usage.cacheWriteTokens : 0);
}

export type ContextShare = {
  key: "system" | "conversation" | "tools" | "definitions" | "output";
  label: string;
  tokens: number;
};

type StoredMessage = { role?: unknown; content?: unknown; tool_calls?: unknown; from_history?: unknown };

/** A rough token count for text: about four characters a token for English prose and code. */
function estimate(value: unknown): number {
  if (value === null || value === undefined) return 0;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return Math.ceil(text.length / 4);
}

/**
 * Splits the latest request's input by where it came from, using the stored messages' lengths: the system prompt,
 * the messages (user and assistant turns), tool results, and the rest (tool definitions and formatting), then
 * the response. Message lengths are only an estimate, so the input shares are scaled to the measured input total.
 */
export function contextShares(usage: ContextUsage, messages: readonly unknown[] | undefined): ContextShare[] {
  const input = inputTokens(usage);
  if (messages === undefined) {
    return [
      { key: "conversation", label: "Messages", tokens: input },
      { key: "output", label: "Latest response", tokens: usage.outputTokens },
    ];
  }
  const sums = { system: 0, conversation: 0, tools: 0 };
  for (const raw of messages) {
    if (typeof raw !== "object" || raw === null) continue;
    const message = raw as StoredMessage;
    const size = estimate(message.content) + estimate(message.tool_calls);
    if (message.role === "system" || message.role === "developer") sums.system += size;
    else if (message.role === "tool") sums.tools += size;
    else sums.conversation += size;
  }
  // The last message is the model's response: it is the output, not part of the input that produced it.
  const last = messages.at(-1) as StoredMessage | undefined;
  if (last?.role === "assistant") {
    sums.conversation = Math.max(0, sums.conversation - estimate(last.content) - estimate(last.tool_calls));
  }
  const estimated = sums.system + sums.conversation + sums.tools;
  const scale = estimated > input && estimated > 0 ? input / estimated : 1;
  const system = Math.round(sums.system * scale);
  const conversation = Math.round(sums.conversation * scale);
  const tools = Math.round(sums.tools * scale);
  return [
    { key: "system", label: "System prompt", tokens: system },
    { key: "conversation", label: "Messages", tokens: conversation },
    { key: "tools", label: "Tool results", tokens: tools },
    {
      key: "definitions",
      label: "Tool definitions",
      tokens: Math.max(0, input - system - conversation - tools),
    },
    { key: "output", label: "Latest response", tokens: usage.outputTokens },
  ];
}

/** The context usage a stored run reports: its last model message's counts, or the run's own for one call. */
export function storedContext(
  messages: readonly unknown[] | null | undefined,
  metrics: Record<string, unknown> | null | undefined,
): ContextUsage | undefined {
  const details = metrics?.details as Record<string, { id?: string; provider?: string }[]> | undefined;
  const model = details?.model?.[0];
  const counts = (source: Record<string, unknown>): ContextUsage | undefined => {
    const value = (key: string) => (typeof source[key] === "number" ? source[key] : 0);
    if (value("input_tokens") === 0) return undefined;
    return {
      inputTokens: value("input_tokens"),
      outputTokens: value("output_tokens"),
      cacheReadTokens: value("cache_read_tokens"),
      cacheWriteTokens: value("cache_write_tokens"),
      reasoningTokens: value("reasoning_tokens"),
      model: model?.id,
      provider: model?.provider,
    };
  };
  for (const raw of [...(messages ?? [])].reverse()) {
    if (typeof raw !== "object" || raw === null) continue;
    const message = raw as { role?: unknown; metrics?: unknown };
    if (message.role !== "assistant" || typeof message.metrics !== "object" || message.metrics === null)
      continue;
    const usage = counts(message.metrics as Record<string, unknown>);
    if (usage) return usage;
  }
  // No per-message counts: the run's totals are exact only when the run made a single model call.
  const toolCalls = (messages ?? []).filter(
    (raw) => typeof raw === "object" && raw !== null && (raw as StoredMessage).role === "tool",
  ).length;
  return metrics && toolCalls === 0 ? counts(metrics) : undefined;
}
