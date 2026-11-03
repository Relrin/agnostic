// Queue data: polled queries over /queue/*, recovery mutations, and formatting shared by the page and the job aside.
import {
  isProblem,
  queueCancelJobMutation,
  queueQueueJobOptions,
  queueQueueJobQueryKey,
  queueQueueJobsOptions,
  queueQueueOverviewOptions,
  queueQueueSummaryOptions,
  queueRequeueJobMutation,
  queueResumeJobMutation,
  type QueueJobDetailOut,
} from "@agnostic/api";
import { toDate, withQueryFn } from "@agnostic/core";
import type { EntityKind } from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

/** Health, workers and jobs refresh this often while the tab is visible. */
export const POLL_MS = 10_000;
export const PAGE_SIZE = 50;

export const JOB_STATUSES = ["queued", "running", "paused", "failed", "completed", "cancelled"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
export type StatusTab = JobStatus | "all";

export const TAB_LABEL: Record<StatusTab, string> = {
  all: "All",
  queued: "Pending",
  running: "Running",
  paused: "Paused",
  failed: "Failed",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** Jobs that are done: nothing left to cancel. */
export const FINISHED: readonly string[] = ["failed", "completed", "cancelled"];

export function useQueueSummary(instance: string) {
  return useQuery({
    ...withQueryFn(queueQueueSummaryOptions({ path: { instance } })),
    enabled: Boolean(instance),
    refetchInterval: POLL_MS,
  });
}

export function useQueueOverview(instance: string, enabled: boolean) {
  return useQuery({
    ...withQueryFn(queueQueueOverviewOptions({ path: { instance } })),
    enabled: Boolean(instance) && enabled,
    refetchInterval: POLL_MS,
  });
}

export function useQueueJobs(instance: string, status: StatusTab, page: number, enabled: boolean) {
  return useQuery({
    ...withQueryFn(
      queueQueueJobsOptions({
        path: { instance },
        query: { ...(status === "all" ? {} : { status }), page, limit: PAGE_SIZE },
      }),
    ),
    enabled: Boolean(instance) && enabled,
    refetchInterval: POLL_MS,
  });
}

export function useQueueJob(instance: string, jobId: string) {
  return useQuery({
    ...withQueryFn(queueQueueJobOptions({ path: { instance, job_id: jobId } })),
    enabled: Boolean(instance && jobId),
    refetchInterval: POLL_MS,
  });
}

/** Refetch everything the queue page shows (after an action, or the Refresh button). */
export async function invalidateQueue(queryClient: QueryClient): Promise<void> {
  await Promise.all(
    ["queueQueueSummary", "queueQueueOverview", "queueQueueJobs", "queueQueueJob"].map((id) =>
      queryClient.invalidateQueries({ queryKey: [{ _id: id }] }),
    ),
  );
}

/** Resume from a checkpoint, requeue (optionally forced), cancel; each answers with the job's new detail. */
export function useJobActions(instance: string, jobId: string) {
  const queryClient = useQueryClient();
  const settle = (detail: QueueJobDetailOut) => {
    queryClient.setQueryData(queueQueueJobQueryKey({ path: { instance, job_id: jobId } }), detail);
    void invalidateQueue(queryClient);
  };
  return {
    resume: useMutation({ ...queueResumeJobMutation(), onSuccess: settle }),
    requeue: useMutation({ ...queueRequeueJobMutation(), onSuccess: settle }),
    cancel: useMutation({ ...queueCancelJobMutation(), onSuccess: settle }),
  };
}

export function isConflict(error: unknown): boolean {
  return isProblem(error) && error.status === 409;
}

/** "agent", "agents", "Team" → the entity kind; unknown types → undefined. */
export function kindOf(componentType: string | null | undefined): EntityKind | undefined {
  const kind = (componentType ?? "").toLowerCase().replace(/s$/, "");
  return kind === "agent" || kind === "team" || kind === "workflow" ? kind : undefined;
}

/** A number from the bridge's QueueConfig, when it reports one. */
export function configNumber(config: Record<string, unknown> | undefined, key: string): number | undefined {
  const value = config?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function configText(config: Record<string, unknown> | undefined, key: string): string | undefined {
  const value = config?.[key];
  return typeof value === "string" && value ? value : undefined;
}

/** 3 → "3s", 2460 → "41m", 8040 → "2h 14m", 50400 → "14h", 259200 → "3d". */
export function formatAge(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${String(total)}s`;
  if (total < 3600) return `${String(Math.floor(total / 60))}m`;
  if (total < 86_400) {
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    return minutes ? `${String(hours)}h ${String(minutes).padStart(2, "0")}m` : `${String(hours)}h`;
  }
  return `${String(Math.floor(total / 86_400))}d`;
}

/** Seconds since `value`, or undefined when it isn't a date. */
export function secondsSince(value: string | null | undefined, now: number = Date.now()): number | undefined {
  const date = toDate(value);
  return date ? Math.max(0, (now - date.getTime()) / 1000) : undefined;
}

/** A configured duration: 60 → "60 s", 86400 → "24 h", 604800 → "7 d". */
export function formatSeconds(seconds: number): string {
  if (seconds >= 3 * 86_400 && seconds % 86_400 === 0) return `${String(seconds / 86_400)} d`;
  if (seconds >= 3600 && seconds % 3600 === 0) return `${String(seconds / 3600)} h`;
  if (seconds >= 120 && seconds % 60 === 0) return `${String(seconds / 60)} min`;
  return `${String(seconds)} s`;
}

/** "16:24:07 UTC". */
export function utcTime(value: string | null | undefined): string | undefined {
  const date = toDate(value);
  return date ? `${date.toISOString().slice(11, 19)} UTC` : undefined;
}
