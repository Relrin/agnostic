// Coding agents: agents that run each turn through a coding harness (Pi, OpenCode) inside a per-session sandbox.
// The list comes from agnostic-bridge on the instance (`/agnostic/v1/coding-agents`, read through the gateway as the
// person), and only when the bridge says it serves that route: older bridges and runtimes without coding agents
// are never asked.
import { gatewayJson } from "@agnostic/api";
import { skipToken, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import type { ComponentSummary } from "../agentos";
import { STALE_TIME } from "../query";

export type CodingHarness = "pi" | "opencode";
export type SandboxProvider = "docker" | "e2b";

export type CodingSandbox = {
  provider: SandboxProvider;
  image?: string | null | undefined;
  network?: string | null | undefined;
  cpus?: number | null | undefined;
  memory_mb?: number | null | undefined;
  turn_timeout_s?: number | null | undefined;
};

/** One coding agent, as the bridge lists it. */
export type CodingAgent = {
  id: string;
  name: string;
  harness: CodingHarness;
  source: "code" | "studio";
  version: number | null;
  model: { id: string; provider: string } | null;
  sandbox: CodingSandbox;
  tools: string[];
};

export type CodingAgentList = { items: CodingAgent[] };

/** The part of the bridge's `/agnostic/v1/capabilities` answer the UI reads. */
export type BridgeCapabilities = {
  bridge_version?: string;
  endpoints?: string[];
  features?: { coding_agents?: { enabled?: boolean } | null } & Record<string, unknown>;
};

export const CODING_AGENTS_ENDPOINT = "GET /agnostic/v1/coding-agents";

const codingKeys = {
  capabilities: (instance: string) => [instance, "agentos", "bridge", "capabilities"] as const,
  agents: (instance: string) => [instance, "agentos", "coding-agents"] as const,
};

/** The bridge's capabilities, or an error on runtimes without the bridge (never retried). */
export function useBridgeCapabilities(instance: string | undefined) {
  return useQuery({
    queryKey: codingKeys.capabilities(instance ?? ""),
    queryFn: instance
      ? () => gatewayJson<BridgeCapabilities>(instance, "agnostic/v1/capabilities")
      : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
}

/** Whether the bridge serves the coding-agent list. */
export function codingAgentsEnabled(capabilities: BridgeCapabilities | undefined): boolean {
  if (!capabilities) return false;
  if (capabilities.features?.coding_agents?.enabled === true) return true;
  return capabilities.endpoints?.includes(CODING_AGENTS_ENDPOINT) ?? false;
}

/** The instance's coding agents, keyed by id; empty when the bridge has none or doesn't serve the list. */
export function useCodingAgents(instance: string | undefined) {
  const capabilities = useBridgeCapabilities(instance);
  const enabled = codingAgentsEnabled(capabilities.data);
  const query = useQuery({
    queryKey: codingKeys.agents(instance ?? ""),
    queryFn:
      instance && enabled
        ? () => gatewayJson<CodingAgentList>(instance, "agnostic/v1/coding-agents").then((body) => body.items)
        : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
  const byId = useMemo(
    () => new Map((query.data ?? []).map((agent) => [agent.id, agent] as const)),
    [query.data],
  );
  return { ...query, enabled, byId };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asHarness(value: unknown): CodingHarness | undefined {
  return value === "pi" || value === "opencode" ? value : undefined;
}

/** The coding-agent marker in an agent's metadata (`metadata.agnostic.coding_agent`), if it carries one. */
export function codingMarker(metadata: unknown): Record<string, unknown> | undefined {
  if (!isRecord(metadata)) return undefined;
  const namespace = metadata.agnostic;
  if (!isRecord(namespace)) return undefined;
  const marker = namespace.coding_agent;
  return isRecord(marker) ? marker : undefined;
}

/**
 * The harness a component runs through, or undefined for an ordinary agent: the bridge's list first, then the
 * marker in its metadata, then the `metadata.sdk` the runtime reports for external agents.
 */
export function codingHarnessOf(
  summary: Pick<ComponentSummary, "id" | "family" | "metadata"> | undefined,
  agents?: ReadonlyMap<string, CodingAgent>,
): CodingHarness | undefined {
  if (summary?.family !== "agents") return undefined;
  const listed = agents?.get(summary.id)?.harness;
  if (listed) return listed;
  return asHarness(codingMarker(summary.metadata)?.harness) ?? asHarness(summary.metadata?.sdk);
}
