// What a step's agent or team brings with it, read from its current config: the model and the tools, shown as
// read-only rows on the step's node (they're edited in the agent or team editor), each with its logo. Configs are
// fetched once per executor and shared with the rest of Studio's queries; an executor Studio doesn't store shows
// no rows.
import { studioGetComponentOptions, type RegistryEntryOut } from "@agnostic/api";
import { STALE_TIME, withQueryFn } from "@agnostic/core";
import { isRecord, useRegistry, type Config } from "@agnostic/studio";
import { modelBrand, toolBrand } from "@agnostic/ui";
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import type { DetailsLookup, ExecutorDetails, ToolLook } from "./graph";
import { executorOf, flatten, type Executor } from "./tree";

/** The model as stored: an id (`"openai:gpt-5"` names its provider too) or a `{id, provider}` ref. */
function modelOf(config: Record<string, unknown>): { id?: string; provider?: string } {
  const model = config.model;
  if (typeof model === "string" && model) return { id: model };
  if (isRecord(model) && typeof model.id === "string") {
    return { id: model.id, ...(typeof model.provider === "string" ? { provider: model.provider } : {}) };
  }
  return {};
}

/** The tools as the agent editor shows them: one per toolkit (its functions together), else one per tool. */
function toolsOf(config: Record<string, unknown>): string[] {
  const tools = Array.isArray(config.tools) ? config.tools : [];
  const names = tools.flatMap((tool): string[] => {
    if (typeof tool === "string") return [tool];
    if (isRecord(tool) && typeof tool.toolkit === "string") return [tool.toolkit];
    if (isRecord(tool) && typeof tool.name === "string") return [tool.name];
    return [];
  });
  return [...new Set(names)];
}

type FindTool = (name: string) => RegistryEntryOut | undefined;

/** How a tool block looks: its registry entry says where it comes from and which logo it has. */
export function lookOf(name: string, entry: RegistryEntryOut | undefined): ToolLook {
  const catalog = entry?.catalog;
  const kind = catalog?.kind ?? "code";
  const brand = toolBrand({
    icon: catalog?.icon,
    kind: catalog?.kind,
    toolkitKey: catalog?.toolkit_key,
    hints: [catalog?.display_name, name],
  });
  return brand ? { kind, brand } : { kind };
}

/** An agent's or team's model and tools, from a stored config (with their logos when `find` knows the tools). */
export function detailsOf(config: unknown, find?: FindTool): ExecutorDetails | undefined {
  if (!isRecord(config)) return undefined;
  const model = modelOf(config);
  const tools = toolsOf(config);
  if (!model.id && tools.length === 0) return undefined;
  const brand = model.id ? modelBrand(model) : undefined;
  return {
    model: model.id,
    ...(brand ? { modelBrand: brand } : {}),
    tools,
    ...(find ? { looks: Object.fromEntries(tools.map((tool) => [tool, lookOf(tool, find(tool))])) } : {}),
  };
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
  const registry = useRegistry(instance);
  const findTool = registry.find;
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
      const details = detailsOf(configs[index], (name) => findTool("tool", name));
      return details ? [[executor.id, details] as const] : [];
    }),
  );
  return useMemo(() => {
    const found = new Map<string, ExecutorDetails>(JSON.parse(key) as [string, ExecutorDetails][]);
    return (executor: Executor) => found.get(executor.id);
  }, [key]);
}
