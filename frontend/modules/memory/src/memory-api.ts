// AgentOS memory routes through the gateway (as the signed-in person) and the control plane's memory helpers.
// Query keys are `[instance, "agentos", "memory", …]` so a write refreshes everything memory-related at once.
import { gatewayJson, jsonBody, type AgentOS } from "@agnostic/api";
import { STALE_TIME } from "@agnostic/core";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type Memory = AgentOS.UserMemorySchema;
/** The `/config` sections this page reads (the generated type is an open object). */
export type OsConfig = { memory?: AgentOS.MemoryConfig | null };
export type UserStats = AgentOS.UserStatsSchema;

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const memoryKeys = {
  all: (instance: string) => [instance, "agentos", "memory"] as const,
  config: (instance: string) => [instance, "agentos", "config"] as const,
  users: (instance: string, db: string | undefined) => [instance, "agentos", "memory", "users", db] as const,
  list: (instance: string, params: Record<string, string | undefined>) =>
    [instance, "agentos", "memory", "list", params] as const,
  topics: (instance: string, user: string, db: string | undefined) =>
    [instance, "agentos", "memory", "topics", user, db] as const,
};

/** `/config`: memory databases (several → the Database select) and user isolation. */
export function useConfig(instance: string) {
  return useQuery({
    queryKey: memoryKeys.config(instance),
    queryFn: instance ? () => gatewayJson<OsConfig>(instance, "config") : skipToken,
    staleTime: STALE_TIME.config,
  });
}

/** Database ids from `/config.memory.dbs`, e.g. `["agno-postgres"]`. */
export function memoryDatabases(config: OsConfig | undefined): string[] {
  return (config?.memory?.dbs ?? []).map((db) => db.db_id);
}

export function useUserStats(instance: string, db: string | undefined) {
  return useQuery({
    queryKey: memoryKeys.users(instance, db),
    queryFn: () =>
      gatewayJson<AgentOS.PaginatedResponseUserStatsSchema>(
        instance,
        `user_memory_stats${query({ page: 1, limit: 100, db_id: db })}`,
      ),
    staleTime: STALE_TIME.list,
  });
}

export function useMemories(
  instance: string,
  params: { user: string | undefined; search: string; topic: string | undefined; db: string | undefined },
) {
  return useQuery({
    queryKey: memoryKeys.list(instance, {
      user: params.user,
      search: params.search,
      topic: params.topic,
      db: params.db,
    }),
    queryFn: params.user
      ? () =>
          gatewayJson<AgentOS.PaginatedResponseUserMemorySchema>(
            instance,
            `memories${query({
              user_id: params.user,
              search_content: params.search,
              topics: params.topic,
              db_id: params.db,
              page: 1,
              limit: 100,
              sort_by: "updated_at",
              sort_order: "desc",
            })}`,
          )
      : skipToken,
    staleTime: STALE_TIME.list,
    placeholderData: (previous) => previous,
  });
}

export function useTopics(instance: string, user: string | undefined, db: string | undefined) {
  return useQuery({
    queryKey: memoryKeys.topics(instance, user ?? "", db),
    queryFn: user
      ? () => gatewayJson<string[]>(instance, `memory_topics${query({ user_id: user, db_id: db })}`)
      : skipToken,
    staleTime: STALE_TIME.list,
  });
}

export type MemoryDraft = { memory: string; topics: string[] };

/** Create, update and delete through the gateway; every success refreshes the memory queries. */
export function useMemoryActions(instance: string, db: string | undefined) {
  const client = useQueryClient();
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: memoryKeys.all(instance) });
    await client.invalidateQueries({ queryKey: [{ _id: "contextMemoryDuplicates" }] });
  };
  const suffix = query({ db_id: db });
  const create = useMutation({
    mutationFn: ({ user, draft }: { user: string; draft: MemoryDraft }) =>
      gatewayJson<Memory>(instance, `memories${suffix}`, {
        method: "POST",
        ...jsonBody({ memory: draft.memory, topics: draft.topics, user_id: user }),
      }),
    onSuccess: refresh,
  });
  const update = useMutation({
    mutationFn: ({ id, user, draft }: { id: string; user: string; draft: MemoryDraft }) =>
      gatewayJson<Memory>(instance, `memories/${encodeURIComponent(id)}${suffix}`, {
        method: "PATCH",
        ...jsonBody({ memory: draft.memory, topics: draft.topics, user_id: user }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: ({ id }: { id: string }) =>
      gatewayJson(instance, `memories/${encodeURIComponent(id)}${suffix}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return { create, update, remove, refresh };
}

/** Topics of the loaded memories, most used first: the pills after "All". */
export function topicCounts(memories: readonly Memory[]): { topic: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const memory of memories)
    for (const topic of memory.topics ?? []) counts.set(topic, (counts.get(topic) ?? 0) + 1);
  return [...counts.entries()]
    .map(([topic, count]) => ({ topic, count }))
    .sort((a, b) => b.count - a.count || a.topic.localeCompare(b.topic));
}

/** "support-triage, billing-agent and kb-researcher". */
export function authors(memories: readonly Memory[]): string {
  const names = [
    ...new Set(
      memories.flatMap((memory) =>
        (memory.agent_id ?? memory.team_id) ? [memory.agent_id ?? memory.team_id ?? ""] : [],
      ),
    ),
  ];
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1) ?? ""}`;
}
