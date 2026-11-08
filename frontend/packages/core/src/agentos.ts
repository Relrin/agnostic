// AgentOS reads shared by Chat, Sessions and Home, through the gateway as the signed-in person (user isolation and
// scopes apply). Query keys are `[instance, "agentos", …]`.
import { gatewayJson, jsonBody, type AgentOS } from "@agnostic/api";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { STALE_TIME } from "./query";
import type { RunFamily } from "./run-stream/run-stream";

export type ComponentSummary = {
  id: string;
  name: string;
  family: RunFamily;
  description?: string | undefined;
  currentVersion?: number | undefined;
  isComponent: boolean;
  /** Team members (names), for "@ Mention member". */
  members?: string[] | undefined;
  /** The component's metadata as the runtime reports it (`sdk` for external agents, Agnostic's markers). */
  metadata?: Record<string, unknown> | undefined;
  /** The model the component runs on (`gpt-4.1`, `claude-sonnet-4-5`), when the runtime says. */
  model?: string | undefined;
};

export type SessionsQuery = {
  type?: "agent" | "team" | "workflow" | undefined;
  componentId?: string | undefined;
  userId?: string | undefined;
  name?: string | undefined;
  page?: number | undefined;
  limit?: number | undefined;
  sortBy?: string | undefined;
  sortOrder?: "asc" | "desc" | undefined;
};

export const SESSION_TYPE: Record<RunFamily, "agent" | "team" | "workflow"> = {
  agents: "agent",
  teams: "team",
  workflows: "workflow",
};

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const agentosKeys = {
  all: (instance: string) => [instance, "agentos"] as const,
  components: (instance: string, family: RunFamily) => [instance, "agentos", "components", family] as const,
  versions: (instance: string, componentId: string) =>
    [instance, "agentos", "versions", componentId] as const,
  sessions: (instance: string, params: SessionsQuery) => [instance, "agentos", "sessions", params] as const,
  session: (instance: string, sessionId: string) => [instance, "agentos", "session", sessionId] as const,
  runs: (instance: string, sessionId: string) => [instance, "agentos", "session-runs", sessionId] as const,
};

/** `GET /agents|teams|workflows`: what this person may run (AgentOS filters by per-component grants). */
export function useComponents(instance: string | undefined, family: RunFamily) {
  return useQuery({
    queryKey: agentosKeys.components(instance ?? "", family),
    queryFn: instance
      ? async (): Promise<ComponentSummary[]> => {
          const items = await gatewayJson<
            (AgentOS.AgentResponse | AgentOS.TeamResponse | AgentOS.WorkflowResponse)[]
          >(instance, family);
          return items.flatMap((item) => {
            const id = item.id;
            if (!id) return [];
            const extra = item as {
              current_version?: number | null;
              is_component?: boolean;
              description?: string | null;
              members?: { name?: string | null; id?: string | null }[] | null;
              metadata?: Record<string, unknown> | null;
              model?: { model?: string | null } | null;
            };
            return [
              {
                id,
                name: item.name ?? id,
                family,
                description: extra.description ?? undefined,
                currentVersion: extra.current_version ?? undefined,
                isComponent: extra.is_component ?? false,
                members: extra.members?.flatMap((member) => {
                  const name = member.name ?? member.id;
                  return name ? [name] : [];
                }),
                metadata: extra.metadata ?? undefined,
                model: extra.model?.model ?? undefined,
              },
            ];
          });
        }
      : skipToken,
    staleTime: STALE_TIME.config,
  });
}

/** Published and draft versions of a DB-backed component (`/components/{id}/configs`). */
export function useComponentVersions(
  instance: string | undefined,
  componentId: string | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: agentosKeys.versions(instance ?? "", componentId ?? ""),
    queryFn:
      instance && componentId && enabled
        ? async () => {
            const body = await gatewayJson<
              AgentOS.ComponentConfigResponse[] | { data?: AgentOS.ComponentConfigResponse[] }
            >(instance, `components/${encodeURIComponent(componentId)}/configs`);
            const items = Array.isArray(body) ? body : (body.data ?? []);
            return [...items].sort((a, b) => b.version - a.version);
          }
        : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
}

export function useSessions(instance: string | undefined, params: SessionsQuery, enabled = true) {
  return useQuery({
    queryKey: agentosKeys.sessions(instance ?? "", params),
    queryFn:
      instance && enabled
        ? () =>
            gatewayJson<AgentOS.PaginatedResponseSessionSchema>(
              instance,
              `sessions${query({
                type: params.type,
                component_id: params.componentId,
                user_id: params.userId,
                session_name: params.name,
                page: params.page,
                limit: params.limit ?? 20,
                sort_by: params.sortBy ?? "updated_at",
                sort_order: params.sortOrder ?? "desc",
              })}`,
            )
        : skipToken,
    staleTime: STALE_TIME.list,
    placeholderData: (previous) => previous,
  });
}

export type SessionDetail =
  AgentOS.AgentSessionDetailSchema | AgentOS.TeamSessionDetailSchema | AgentOS.WorkflowSessionDetailSchema;

export function useSession(instance: string | undefined, sessionId: string | undefined, type?: string) {
  return useQuery({
    queryKey: agentosKeys.session(instance ?? "", sessionId ?? ""),
    queryFn:
      instance && sessionId
        ? () =>
            gatewayJson<SessionDetail>(
              instance,
              `sessions/${encodeURIComponent(sessionId)}${query({ type })}`,
            )
        : skipToken,
    staleTime: STALE_TIME.list,
    retry: false,
  });
}

export function useSessionRuns(instance: string | undefined, sessionId: string | undefined, type?: string) {
  return useQuery({
    queryKey: agentosKeys.runs(instance ?? "", sessionId ?? ""),
    queryFn:
      instance && sessionId
        ? async () => {
            const body = await gatewayJson<
              | (AgentOS.RunSchema | AgentOS.TeamRunSchema | AgentOS.WorkflowRunSchema)[]
              | { data?: AgentOS.RunSchema[] }
            >(instance, `sessions/${encodeURIComponent(sessionId)}/runs${query({ type })}`);
            return Array.isArray(body) ? body : (body.data ?? []);
          }
        : skipToken,
    staleTime: STALE_TIME.live,
    retry: false,
  });
}

/** Rename, delete, update state and fork a session; every success refreshes the instance's session queries. */
export function useSessionActions(instance: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: agentosKeys.all(instance) });
  const rename = useMutation({
    mutationFn: ({ sessionId, name }: { sessionId: string; name: string }) =>
      gatewayJson(instance, `sessions/${encodeURIComponent(sessionId)}/rename`, {
        method: "POST",
        ...jsonBody({ session_name: name }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) =>
      gatewayJson(instance, `sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const updateState = useMutation({
    mutationFn: ({ sessionId, state }: { sessionId: string; state: Record<string, unknown> }) =>
      gatewayJson(instance, `sessions/${encodeURIComponent(sessionId)}`, {
        method: "PATCH",
        ...jsonBody({ session_state: state }),
      }),
    onSuccess: refresh,
  });
  const fork = useMutation({
    mutationFn: ({
      sessionId,
      family,
      componentId,
    }: {
      sessionId: string;
      family: "agents" | "teams";
      componentId: string;
    }) =>
      gatewayJson<{ session_id?: string }>(
        instance,
        `${family}/${encodeURIComponent(componentId)}/sessions/${encodeURIComponent(sessionId)}/fork`,
        { method: "POST" },
      ),
    onSuccess: refresh,
  });
  return { rename, remove, updateState, fork };
}
