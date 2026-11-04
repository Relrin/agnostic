// Scheduler data: the schedule list (with optimistic enable/disable), run history, the cron preview (debounced, so
// typing in the cron fields doesn't flood the API), endpoint checks, and time formatting in a schedule's timezone.
import {
  describeError,
  schedulerCheckEndpointOptions,
  schedulerCreateSchedule,
  schedulerDeleteSchedule,
  schedulerDisableSchedule,
  schedulerEnableSchedule,
  schedulerListSchedulesOptions,
  schedulerPreviewSchedule,
  schedulerScheduleRunsOptions,
  schedulerSchedulerStatusOptions,
  schedulerTriggerSchedule,
  schedulerUpdateSchedule,
  type Method,
  type PreviewOut,
  type ScheduleIn,
  type ScheduleOut,
  type SchedulePatch,
  type SchedulesPageOut,
} from "@agnostic/api";
import { STALE_TIME } from "@agnostic/core";
import { toast } from "@agnostic/ui";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type Schedule = ScheduleOut;
export type TargetKind = "agent" | "team" | "workflow";

export const METHODS: readonly Method[] = ["POST", "GET", "PUT", "PATCH", "DELETE"];
export const FAMILY: Record<TargetKind, "agents" | "teams" | "workflows"> = {
  agent: "agents",
  team: "teams",
  workflow: "workflows",
};
export const NAME_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$/;

const LIST_KEY = [{ _id: "schedulerListSchedules" }];
const RUNS_KEY = [{ _id: "schedulerScheduleRuns" }];

function listOptions(instance: string) {
  return schedulerListSchedulesOptions({ path: { instance }, query: { limit: 100 } });
}

export function useSchedules(instance: string) {
  const options = listOptions(instance);
  return useQuery({
    ...options,
    queryFn: instance ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.list,
  });
}

export function useSchedulerStatus(instance: string) {
  const options = schedulerSchedulerStatusOptions({ path: { instance } });
  return useQuery({
    ...options,
    queryFn: instance ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.list,
  });
}

export function useScheduleRuns(instance: string, scheduleId: string) {
  const options = schedulerScheduleRunsOptions({
    path: { instance, schedule_id: scheduleId },
    query: { limit: 20 },
  });
  return useQuery({
    ...options,
    queryFn: instance ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.list,
  });
}

/** `value`, once it has stopped changing for `delay` ms. */
export function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return settled;
}

/** The human sentence, the next 5 runs and DST notes for a cron expression in a timezone (debounced). */
export function usePreview(instance: string, cron: string, timezone: string) {
  const key = useDebounced(`${cron.trim()}\n${timezone}`, 300);
  const [expression = "", zone = "UTC"] = key.split("\n");
  return useQuery({
    queryKey: [instance, "scheduler", "preview", expression, zone],
    queryFn:
      instance && expression
        ? async (): Promise<PreviewOut> =>
            (
              await schedulerPreviewSchedule({
                path: { instance },
                body: { cron_expr: expression, timezone: zone, count: 5 },
                throwOnError: true,
              })
            ).data
        : skipToken,
    staleTime: 60_000,
    retry: false,
  });
}

export type Preview = ReturnType<typeof usePreview>;

/** Cron fields the server rejected ("minute", "timezone"), from a 422 problem's `fields`. */
export function invalidFields(error: unknown): string[] {
  if (typeof error !== "object" || error === null || !("fields" in error)) return [];
  const fields = error.fields;
  return Array.isArray(fields) ? fields.filter((item): item is string => typeof item === "string") : [];
}

/** Field name → message, from a 422 problem's `errors` (request validation). */
export function fieldErrors(error: unknown): Record<string, string> {
  if (typeof error !== "object" || error === null || !("errors" in error)) return {};
  const errors = error.errors;
  if (!Array.isArray(errors)) return {};
  const result: Record<string, string> = {};
  for (const item of errors) {
    if (typeof item !== "object" || item === null) continue;
    const { loc, msg } = item as { loc?: unknown[]; msg?: string };
    const field = loc?.[loc.length - 1];
    if (typeof field === "string" && msg) result[field] = msg;
  }
  return result;
}

/** What the instance's OpenAPI document says about a custom endpoint (debounced). */
export function useEndpointCheck(instance: string, method: Method, path: string, enabled: boolean) {
  const settled = useDebounced(path.trim(), 400);
  const options = schedulerCheckEndpointOptions({ path: { instance }, query: { path: settled, method } });
  return useQuery({
    ...options,
    queryFn: enabled && instance && settled.startsWith("/") ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.config,
    retry: false,
  });
}

type Toggle = { schedule: Schedule; enabled: boolean; reason?: string | undefined };

/** Enable/disable (optimistic), trigger, create, update and delete; every success refreshes the list. */
export function useScheduleActions(instance: string) {
  const client = useQueryClient();
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: LIST_KEY });
    await client.invalidateQueries({ queryKey: RUNS_KEY });
  };
  const listKey = listOptions(instance).queryKey;
  const patchRow = (id: string, change: (row: Schedule) => Schedule) => {
    client.setQueryData<SchedulesPageOut>(listKey, (page) =>
      page ? { ...page, data: page.data.map((row) => (row.id === id ? change(row) : row)) } : page,
    );
  };

  const setEnabled = useMutation({
    mutationFn: async ({ schedule, enabled, reason }: Toggle) => {
      const path = { instance, schedule_id: schedule.id };
      return enabled
        ? (await schedulerEnableSchedule({ path, throwOnError: true })).data
        : (
            await schedulerDisableSchedule({
              path,
              body: { reason: reason?.trim() ? reason.trim() : null },
              throwOnError: true,
            })
          ).data;
    },
    onMutate: async ({ schedule, enabled }) => {
      await client.cancelQueries({ queryKey: listKey });
      const previous = client.getQueryData<SchedulesPageOut>(listKey);
      patchRow(schedule.id, (row) => ({ ...row, enabled }));
      return { previous };
    },
    onError: (problem, _variables, context) => {
      if (context?.previous) client.setQueryData(listKey, context.previous);
      toast.error(describeError(problem).reason);
    },
    onSuccess: (updated) => {
      patchRow(updated.id, () => updated);
    },
    onSettled: () => client.invalidateQueries({ queryKey: LIST_KEY }),
  });

  const trigger = useMutation({
    mutationFn: async (schedule: Schedule) =>
      (await schedulerTriggerSchedule({ path: { instance, schedule_id: schedule.id }, throwOnError: true }))
        .data,
    onSuccess: refresh,
  });

  const create = useMutation({
    mutationFn: async (body: ScheduleIn) =>
      (await schedulerCreateSchedule({ path: { instance }, body, throwOnError: true })).data,
    onSuccess: refresh,
  });

  const update = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: SchedulePatch }) =>
      (await schedulerUpdateSchedule({ path: { instance, schedule_id: id }, body, throwOnError: true })).data,
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: async (schedule: Schedule) => {
      await schedulerDeleteSchedule({ path: { instance, schedule_id: schedule.id }, throwOnError: true });
    },
    onSuccess: refresh,
  });

  return { setEnabled, trigger, create, update, remove };
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** An ISO timestamp's own wall time (the offset it carries), e.g. "Mon 2 Nov 2026" and "08:00". */
export function wallTime(iso: string): { date: string; time: string } {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return { date: iso, time: "" };
  const [, year = "", month = "", day = "", hour = "", minute = ""] = match;
  const weekday =
    WEEKDAYS[new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))).getUTCDay()] ?? "";
  return {
    date: `${weekday} ${String(Number(day))} ${MONTHS[Number(month) - 1] ?? month} ${year}`,
    time: `${hour}:${minute}`,
  };
}

/** "once", "twice", "3 times". */
export function times(count: number): string {
  return count === 1 ? "once" : count === 2 ? "twice" : `${String(count)} times`;
}

/** The target of a schedule as one line: "workflow · daily-brief", or "Custom endpoint". */
export function targetLabel(schedule: Pick<Schedule, "target_kind" | "target_id">): string {
  return schedule.target_kind === "custom"
    ? "Custom endpoint"
    : `${schedule.target_kind} · ${schedule.target_id ?? "—"}`;
}
