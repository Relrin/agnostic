// Queries, mutations and labels shared by the Sources page and the connect wizard.
import {
  sourcesGetChangesOptions,
  sourcesListConnectionsOptions,
  sourcesListSourcesOptions,
  type CodeSourceOut,
} from "@agnostic/api";
import { STALE_TIME, withQueryFn } from "@agnostic/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";

export const TARGET_LABEL: Record<string, string> = {
  agents: "Agents",
  teams: "Agent teams",
  workflows: "Workflows",
  registry: "Registry",
  ignored: "Ignored",
};

export const PULL_MODES = [
  { value: "on_demand", label: "On demand" },
  { value: "on_push_as_drafts", label: "On every push, as drafts" },
] as const;

export const PUBLISH_MODES = [
  { value: "open_pr", label: "Open a pull request" },
  { value: "commit_direct", label: "Commit directly to the branch" },
  { value: "no_write_back", label: "Don't write back" },
] as const;

export function useSources(instance: string) {
  return useQuery({
    ...withQueryFn(sourcesListSourcesOptions({ path: { instance } })),
    staleTime: STALE_TIME.list,
    // A new source scans in the background: keep looking until it is ready.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((source) => source.status === "scanning" || source.status === "setup")
        ? 1500
        : false,
  });
}

export function useChanges(instance: string, sourceId: string | undefined) {
  return useQuery({
    ...withQueryFn(sourcesGetChangesOptions({ path: { instance, source_id: sourceId ?? "" } })),
    enabled: Boolean(sourceId),
    staleTime: STALE_TIME.list,
  });
}

export function useConnections(enabled = true) {
  return useQuery({ ...withQueryFn(sourcesListConnectionsOptions()), enabled, staleTime: STALE_TIME.list });
}

/** Everything the page shows comes from `sources*` queries: refresh them all after a change. */
export function useRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({
      predicate: (query) => {
        const [first] = query.queryKey;
        return (
          typeof first === "object" &&
          first !== null &&
          "_id" in first &&
          String(first._id).startsWith("sources")
        );
      },
    });
  };
}

/** The chips on a source card, in the design's order and colors. */
export function chips(
  source: CodeSourceOut,
): { label: string; tone: "info" | "warning" | "danger" | "success" | "muted" }[] {
  const found: { label: string; tone: "info" | "warning" | "danger" | "success" | "muted" }[] = [];
  if (source.status === "scanning" || source.status === "setup")
    found.push({ label: "scanning…", tone: "muted" });
  if (source.status === "ready") found.push({ label: "scan ready · not syncing yet", tone: "warning" });
  if (source.status === "failed") found.push({ label: "fetch failed", tone: "danger" });
  if (source.status === "over_quota") found.push({ label: "over quota", tone: "danger" });
  if (source.incoming) found.push({ label: `↓ ${String(source.incoming)} incoming`, tone: "info" });
  if (source.outgoing) found.push({ label: `↑ ${String(source.outgoing)} outgoing`, tone: "warning" });
  if (source.conflicts) {
    found.push({
      label: `${String(source.conflicts)} conflict${source.conflicts === 1 ? "" : "s"}`,
      tone: "danger",
    });
  }
  if (source.status === "active" && !source.incoming && !source.outgoing && !source.conflicts) {
    const files = source.mappings.reduce((total, mapping) => total + (mapping.count ?? 0), 0);
    found.push({
      label: source.provider === "local" ? `in sync · ${String(files)} files` : "up to date",
      tone: "success",
    });
  }
  if (source.auth.endsWith("pull only")) found.push({ label: "read-only", tone: "muted" });
  if (source.provider === "local" || source.webhook) found.push({ label: "watching", tone: "muted" });
  return found;
}
