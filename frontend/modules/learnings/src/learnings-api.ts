// AgentOS learning routes through the gateway (as the signed-in person). Query keys are
// `[instance, "agentos", "learnings", …]`; writes also refresh the control plane's per-type counts.
import { gatewayJson, jsonBody, type AgentOS } from "@agnostic/api";
import { STALE_TIME } from "@agnostic/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type Learning = AgentOS.LearningResponse;

export const LEARNING_TYPES = [
  "user_profile",
  "user_memory",
  "session_context",
  "entity_memory",
  "decision_log",
] as const;
export type LearningType = (typeof LEARNING_TYPES)[number];

export type LearningFilters = {
  type: LearningType;
  user?: string | undefined;
  agent?: string | undefined;
  namespace?: string | undefined;
  entityType?: string | undefined;
  page: number;
};

export const PAGE_SIZE = 20;
export const COUNTS_KEY = [{ _id: "contextLearningCounts" }];

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const learningKeys = {
  all: (instance: string) => [instance, "agentos", "learnings"] as const,
  list: (instance: string, filters: LearningFilters) =>
    [instance, "agentos", "learnings", "list", filters] as const,
};

export function useLearnings(instance: string, filters: LearningFilters) {
  return useQuery({
    queryKey: learningKeys.list(instance, filters),
    queryFn: () =>
      gatewayJson<AgentOS.PaginatedResponseLearningResponse>(
        instance,
        `learnings${query({
          learning_type: filters.type,
          user_id: filters.user,
          agent_id: filters.agent,
          namespace: filters.namespace,
          entity_type: filters.type === "entity_memory" ? filters.entityType : undefined,
          page: filters.page,
          limit: PAGE_SIZE,
          sort_by: "updated_at",
          sort_order: "desc",
        })}`,
      ),
    staleTime: STALE_TIME.list,
    placeholderData: (previous) => previous,
  });
}

export type NewLearning = AgentOS.LearningCreate;

/** Create, replace (content + metadata) and delete; every success refreshes the lists and counts. */
export function useLearningActions(instance: string) {
  const client = useQueryClient();
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: learningKeys.all(instance) });
    await client.invalidateQueries({ queryKey: COUNTS_KEY });
  };
  const create = useMutation({
    mutationFn: (body: NewLearning) =>
      gatewayJson<Learning>(instance, "learnings", { method: "POST", ...jsonBody(body) }),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: ({
      id,
      content,
      metadata,
    }: {
      id: string;
      content: Record<string, unknown>;
      metadata: Record<string, unknown>;
    }) =>
      gatewayJson<Learning>(instance, `learnings/${encodeURIComponent(id)}`, {
        method: "PATCH",
        ...jsonBody({ content, metadata }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: ({ id }: { id: string }) =>
      gatewayJson(instance, `learnings/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return { create, save, remove, refresh };
}

/** "preferred_channel" → "Preferred channel". */
export function humanize(key: string): string {
  const text = key.replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The first value of `content`, as one line: the record's summary in the list. */
export function summary(content: Record<string, unknown> | null | undefined): string {
  const first = Object.values(content ?? {})[0];
  if (first === undefined || first === null) return "—";
  if (Array.isArray(first))
    return first.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join(" · ");
  return typeof first === "string" ? first : JSON.stringify(first);
}
