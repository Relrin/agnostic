// What a step's agent or team brings with it, read from its current config: the model and the tools, shown as
// read-only rows on the step's node (they're edited in the agent or team editor). Configs are fetched once per
// executor and shared with the rest of Studio's queries; an executor Studio doesn't store shows no rows.
import { studioGetComponentOptions } from "@agnostic/api";
import { STALE_TIME, withQueryFn } from "@agnostic/core";
import { isRecord, type Config } from "@agnostic/studio";
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import type { DetailsLookup, ExecutorDetails } from "./graph";
import { executorOf, flatten, type Executor } from "./tree";

function modelOf(config: Record<string, unknown>): string | undefined {
  const model = config.model;
  if (typeof model === "string") return model;
  if (isRecord(model) && typeof model.id === "string") return model.id;
  return undefined;
}

function toolsOf(config: Record<string, unknown>): string[] {
  const tools = Array.isArray(config.tools) ? config.tools : [];
  return tools.flatMap((tool): string[] => {
    if (typeof tool === "string") return [tool];
    if (isRecord(tool) && typeof tool.name === "string") return [tool.name];
    return [];
  });
}

/** An agent's or team's model and tools, from a stored config. */
export function detailsOf(config: unknown): ExecutorDetails | undefined {
  if (!isRecord(config)) return undefined;
  const model = modelOf(config);
  const tools = toolsOf(config);
  return model || tools.length ? { model, tools } : undefined;
}

/** The agents and teams a workflow's steps run. */
export function executorsIn(config: Config | undefined): Executor[] {
  const seen = new Map<string, Executor>();
  for (const item of flatten(config)) {
    const executor = executorOf(item.node);
    if (executor && (executor.kind === "agent" || executor.kind === "team")) {
      seen.set(`${executor.kind}:${executor.id}`, executor);
    }
  }
  return [...seen.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export function useExecutorDetails(instance: string, config: Config | undefined): DetailsLookup {
  const executors = executorsIn(config);
  const configs = useQueries({
    queries: executors.map((executor) => ({
      ...withQueryFn(studioGetComponentOptions({ path: { instance, component_id: executor.id } })),
      staleTime: STALE_TIME.config,
      retry: false,
    })),
    combine: (results) => results.map((result) => result.data?.current?.config ?? result.data?.draft?.config),
  });
  // Keyed on what's known, so the lookup (and the layout reading it) only changes when a model or tool does.
  const key = JSON.stringify(
    executors.flatMap((executor, index) => {
      const details = detailsOf(configs[index]);
      return details ? [[executor.id, details] as const] : [];
    }),
  );
  return useMemo(() => {
    const found = new Map<string, ExecutorDetails>(JSON.parse(key) as [string, ExecutorDetails][]);
    return (executor: Executor) => found.get(executor.id);
  }, [key]);
}
