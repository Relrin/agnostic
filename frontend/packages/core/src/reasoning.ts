// Reasoning effort per run: which levels a component's model takes (from agnostic-bridge, which translates the level
// for the model's provider) and the person's pick, remembered per component in this browser.
import { gatewayJson } from "@agnostic/api";
import { REASONING_LEVELS, type ReasoningLevel } from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { useBridgeCapabilities, type BridgeCapabilities } from "./coding/api";
import { STALE_TIME } from "./query";
import type { RunFamily } from "./run-stream/run-stream";

/** What the bridge answers for one component; `null` when its runs take no reasoning effort. */
export type ReasoningOptions = {
  levels: ReasoningLevel[];
  configured: ReasoningLevel | null;
  parameter: string;
};

export const REASONING_ENDPOINT = "GET /agnostic/v1/reasoning/{family}/{component_id}";

const reasoningKeys = {
  options: (instance: string, family: RunFamily, componentId: string) =>
    [instance, "agentos", "reasoning", family, componentId] as const,
};

/** Whether the bridge on the instance reports reasoning levels (older bridges don't). */
export function reasoningEnabled(capabilities: BridgeCapabilities | undefined): boolean {
  return capabilities?.endpoints?.includes(REASONING_ENDPOINT) ?? false;
}

function isLevel(value: unknown): value is ReasoningLevel {
  return typeof value === "string" && value in REASONING_LEVELS;
}

/** The levels a run of the component may ask for; undefined when there's nothing to choose (or no bridge). */
export function useReasoningOptions(
  instance: string | undefined,
  family: RunFamily,
  componentId: string | undefined,
) {
  const capabilities = useBridgeCapabilities(instance);
  const enabled = family !== "workflows" && reasoningEnabled(capabilities.data);
  const query = useQuery({
    queryKey: reasoningKeys.options(instance ?? "", family, componentId ?? ""),
    queryFn:
      instance && componentId && enabled
        ? async (): Promise<ReasoningOptions | null> => {
            const body = await gatewayJson<ReasoningOptions | null>(
              instance,
              `agnostic/v1/reasoning/${family}/${encodeURIComponent(componentId)}`,
            );
            if (!body) return null;
            const levels = body.levels.filter(isLevel);
            return levels.length > 0
              ? { ...body, levels, configured: isLevel(body.configured) ? body.configured : null }
              : null;
          }
        : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
  return query.data ?? undefined;
}

const STORAGE_PREFIX = "agnostic.reasoning.";

function read(key: string): ReasoningLevel | undefined {
  try {
    const value = window.localStorage.getItem(key);
    return isLevel(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

function write(key: string, value: ReasoningLevel | undefined): void {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    // Storage blocked (private window, policy): the pick lasts until the page reloads.
  }
}

/**
 * The person's reasoning level for a component (undefined: as the component is configured), kept in this browser.
 * A remembered level the model no longer offers reads as undefined.
 */
export function useReasoningChoice(
  instance: string,
  componentId: string | undefined,
  options: ReasoningOptions | undefined,
): [ReasoningLevel | undefined, (value: ReasoningLevel | undefined) => void] {
  const key = `${STORAGE_PREFIX}${instance}.${componentId ?? ""}`;
  const [picks, setPicks] = useState<Record<string, ReasoningLevel | undefined>>({});
  const stored = key in picks ? picks[key] : read(key);
  const value = stored && options?.levels.includes(stored) ? stored : undefined;
  const set = useCallback(
    (next: ReasoningLevel | undefined) => {
      write(key, next);
      setPicks((current) => ({ ...current, [key]: next }));
    },
    [key],
  );
  return [value, set];
}
