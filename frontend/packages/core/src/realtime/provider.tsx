// Wires realtime events into the query cache: badges update in place, lists refetch, access re-evaluates.
import {
  approvalsCountOptions,
  approvalsCountQueryKey,
  notificationsUnreadCountOptions,
  notificationsUnreadCountQueryKey,
  sourcesConflictCountOptions,
  sourcesConflictCountQueryKey,
  type ConflictCountOut,
  type CountOut,
  type UnreadOut,
} from "@agnostic/api";
import { skipToken, useQuery, useQueryClient, type Query } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { STALE_TIME } from "../query";
import { RealtimeClient, type RealtimeListener, type RealtimeMessage } from "./events-client";

const RealtimeContext = createContext<RealtimeClient | undefined>(undefined);

function hasId(query: Query, ids: readonly string[]): boolean {
  const [first] = query.queryKey;
  return typeof first === "object" && first !== null && "_id" in first && ids.includes(String(first._id));
}

/** Query-cache effects of each event type. */
export function applyRealtimeEvent(
  client: ReturnType<typeof useQueryClient>,
  message: RealtimeMessage,
): void {
  const instance = typeof message.data.instance_id === "string" ? message.data.instance_id : undefined;
  switch (message.type) {
    case "approvals.count":
      if (instance && typeof message.data.count === "number") {
        client.setQueryData<CountOut>(approvalsCountQueryKey({ path: { instance } }), {
          instance_id: instance,
          count: message.data.count,
          available: true,
        });
      }
      break;
    case "approval.resolved":
      void client.invalidateQueries({
        predicate: (query) =>
          hasId(query, [
            "approvalsCount",
            "observeOverview",
            "approvalsListApprovals",
            "approvalsApprovalCounts",
            "approvalsGetApproval",
          ]),
      });
      break;
    case "approval.created":
    case "approval.viewed":
      void client.invalidateQueries({
        predicate: (query) =>
          hasId(query, ["approvalsListApprovals", "approvalsApprovalCounts", "approvalsGetApproval"]),
      });
      break;
    case "schedule.failed":
      void client.invalidateQueries({
        predicate: (query) =>
          hasId(query, ["schedulerListSchedules", "schedulerGetSchedule", "observeOverview"]),
      });
      break;
    case "notification.created":
      void client.invalidateQueries({
        predicate: (query) => hasId(query, ["notificationsUnreadCount", "notificationsListNotifications"]),
      });
      break;
    case "notification.read":
      if (typeof message.data.unread === "number") {
        client.setQueryData<UnreadOut>(notificationsUnreadCountQueryKey(), { unread: message.data.unread });
      }
      void client.invalidateQueries({
        predicate: (query) => hasId(query, ["notificationsListNotifications"]),
      });
      break;
    case "access.changed":
      void client.invalidateQueries({ predicate: (query) => hasId(query, ["meMyAccess", "meGetMe"]) });
      break;
    case "instance.health":
      void client.invalidateQueries({ predicate: (query) => hasId(query, ["instancesGetHealth"]) });
      break;
    case "sources.conflicts":
      if (instance && typeof message.data.count === "number") {
        client.setQueryData<ConflictCountOut>(sourcesConflictCountQueryKey({ path: { instance } }), {
          instance_id: instance,
          count: message.data.count,
        });
      }
      break;
    case "sources.changed":
      void client.invalidateQueries({
        predicate: (query) =>
          hasId(query, [
            "sourcesListSources",
            "sourcesGetSource",
            "sourcesGetChanges",
            "sourcesComponentSource",
            "sourcesConflictCount",
          ]),
      });
      break;
    default:
      break;
  }
}

/** Holds the realtime connection while the signed-in shell is mounted. */
export function RealtimeProvider({ children, client }: { children: ReactNode; client?: RealtimeClient }) {
  const queryClient = useQueryClient();
  const [realtime] = useState(() => client ?? new RealtimeClient());
  useEffect(() => {
    const unsubscribe = realtime.subscribe((message) => {
      applyRealtimeEvent(queryClient, message);
    });
    realtime.start();
    return () => {
      unsubscribe();
      realtime.stop();
    };
  }, [queryClient, realtime]);
  return <RealtimeContext.Provider value={realtime}>{children}</RealtimeContext.Provider>;
}

/** Listen to raw realtime events (e.g. a page that reacts to `approval.resolved` for its run). */
export function useRealtimeEvent(listener: RealtimeListener): void {
  const realtime = useContext(RealtimeContext);
  useEffect(() => realtime?.subscribe(listener), [realtime, listener]);
}

/** Pending approvals on the instance (by id): fetched once, then kept current by `approvals.count` events. */
export function useApprovalsCount(instanceId: string | undefined, enabled = true) {
  const options = approvalsCountOptions({ path: { instance: instanceId ?? "" } });
  return useQuery({
    ...options,
    queryFn: instanceId && enabled ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
}

/** Open code-source conflicts on the instance (the sidebar dot): kept current by `sources.conflicts` events. */
export function useSourceConflicts(instanceId: string | undefined, enabled = true) {
  const options = sourcesConflictCountOptions({ path: { instance: instanceId ?? "" } });
  return useQuery({
    ...options,
    queryFn: instanceId && enabled ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
}

/** Unread notifications (the bell): fetched once, then kept current by `notification.*` events. */
export function useUnreadNotifications(enabled = true) {
  const options = notificationsUnreadCountOptions();
  return useQuery({
    ...options,
    queryFn: enabled ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
}
