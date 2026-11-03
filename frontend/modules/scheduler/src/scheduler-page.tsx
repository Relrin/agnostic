import { describeError } from "@agnostic/api";
import { formatCount, useCan } from "@agnostic/core";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  EntitySquare,
  ErrorState,
  LoadingRows,
  StatusPill,
  Switch,
  Tooltip,
  cn,
  toast,
  type Column,
} from "@agnostic/ui";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Plus, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { DisableDialog } from "./schedule-actions";
import { ScheduleDetail } from "./schedule-detail";
import { ScheduleFormDialog } from "./schedule-form";
import {
  formatInZone,
  targetLabel,
  times,
  useScheduleActions,
  useSchedulerStatus,
  useSchedules,
  type Schedule,
} from "./schedules-api";

type Form = { mode: "new" } | { mode: "edit"; schedule: Schedule };

function StatusLine({ running, interval }: { running: boolean | null | undefined; interval: number | null }) {
  if (running === undefined) return null;
  const text =
    running === null
      ? "Scheduler status unknown"
      : running
        ? `Scheduler running${interval ? ` · polls every ${String(interval)} s` : ""}`
        : "Scheduler stopped";
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[12px] text-fg-secondary"
    >
      <span
        aria-hidden
        className={cn(
          "size-[7px] rounded-full",
          running === null ? "bg-fg-muted" : running ? "bg-accent" : "bg-danger",
        )}
      />
      {text}
    </span>
  );
}

function LastRun({ schedule }: { schedule: Schedule }) {
  const last = schedule.last_runs[0];
  if (!last) return <Badge tone="muted">NO RUNS</Badge>;
  const failures = schedule.consecutive_failures;
  if (failures > 1)
    return (
      <Badge tone="danger">
        {last.status.toUpperCase()} ×{failures}
      </Badge>
    );
  return <StatusPill status={last.status} />;
}

function FailureBanner({ instance, schedule }: { instance: string; schedule: Schedule }) {
  const last = schedule.last_runs[0];
  const today = last?.triggered_at
    ? formatInZone(last.triggered_at, schedule.timezone).startsWith("Today")
    : false;
  const error = schedule.last_runs.find((run) => run.error)?.error;
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-tile border border-danger/35 bg-danger/5 px-4 py-3 text-[13px]"
    >
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
      <p className="min-w-0 flex-1">
        <strong className="font-semibold">
          {schedule.name} failed {times(schedule.consecutive_failures)}
          {today ? " today" : " in a row"}.
        </strong>{" "}
        {error ? `${error.replace(/\.$/, "")}. ` : ""}
        {schedule.enabled ? "The schedule is still enabled." : "The schedule is disabled."}
      </p>
      {last?.run_id && (
        <Link
          to={`/i/${encodeURIComponent(instance)}/traces`}
          search={{ run_id: last.run_id }}
          className="shrink-0 text-[12.5px] text-info hover:text-info-hover"
        >
          Open trace
        </Link>
      )}
    </div>
  );
}

/** `/i/:instance/scheduler?schedule=`: cron schedules that start background runs, each in its own timezone. */
export function SchedulerPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instance = params.instance ?? "";
  const selectedId = typeof search.schedule === "string" ? search.schedule : undefined;
  const go = (next: { schedule?: string | undefined }) => {
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/scheduler`,
      search: next.schedule ? { schedule: next.schedule } : {},
    });
  };

  const schedules = useSchedules(instance);
  const status = useSchedulerStatus(instance);
  const actions = useScheduleActions(instance);
  const writeScope = useCan("schedules:write", instance).allowed === true;
  const deleteScope = useCan("schedules:delete", instance).allowed === true;
  const canWrite = status.data ? status.data.can_write : writeScope;
  const canDelete = status.data ? status.data.can_delete : deleteScope;
  const canCustom = status.data?.can_custom_endpoint === true;
  const [disabling, setDisabling] = useState<Schedule | undefined>(undefined);
  const [form, setForm] = useState<Form | undefined>(undefined);

  const rows = schedules.data?.data ?? [];
  const total = schedules.data?.total ?? rows.length;
  const selected = rows.find((row) => row.id === selectedId) ?? rows[0];
  const failing = rows.filter((row) => row.consecutive_failures > 0);

  const setEnabled = (schedule: Schedule, enabled: boolean, reason?: string) => {
    actions.setEnabled.mutate(
      { schedule, enabled, reason },
      {
        onSuccess: () => {
          toast(enabled ? `Enabled ${schedule.name}` : `Disabled ${schedule.name}`, {
            action: {
              label: "Undo",
              onClick: () => {
                actions.setEnabled.mutate({
                  schedule,
                  enabled: !enabled,
                  reason: enabled ? schedule.disabled_note?.reason : undefined,
                });
              },
            },
          });
        },
      },
    );
  };
  const toggle = (schedule: Schedule, enabled: boolean) => {
    if (enabled) setEnabled(schedule, true);
    else setDisabling(schedule);
  };

  const columns: Column<Schedule>[] = [
    {
      id: "schedule",
      header: "SCHEDULE",
      cell: (row) => (
        <div className="flex min-w-0 flex-col gap-1">
          <button
            type="button"
            className="cursor-pointer self-start text-left font-mono text-[12.5px] font-medium hover:underline"
            onClick={(event) => {
              event.stopPropagation();
              go({ schedule: row.id });
            }}
          >
            {row.name}
          </button>
          <span className="flex items-center gap-1.5 text-[12px] text-fg-muted">
            {row.target_kind !== "custom" && <EntitySquare kind={row.target_kind} />}
            {targetLabel(row)}
          </span>
        </div>
      ),
    },
    {
      id: "when",
      header: "WHEN",
      cell: (row) => (
        <div className="flex flex-col gap-1">
          <span className="text-[12.5px]">{row.human ?? row.cron_expr ?? "Only when triggered"}</span>
          {row.cron_expr && (
            <span className="font-mono text-[11.5px] text-fg-muted">
              {row.cron_expr} · {row.timezone}
            </span>
          )}
        </div>
      ),
    },
    {
      id: "next",
      header: "NEXT RUN",
      cell: (row) =>
        row.enabled ? (
          <span className="text-[12.5px] whitespace-nowrap tabular-nums">
            {formatInZone(row.next_run_at, row.timezone)}
          </span>
        ) : (
          <span className="text-[12.5px] text-fg-muted">Disabled</span>
        ),
    },
    {
      id: "last",
      header: "LAST RUN",
      className: "whitespace-nowrap",
      cell: (row) => <LastRun schedule={row} />,
    },
    {
      id: "on",
      header: "ON",
      cell: (row) => (
        // The switch toggles; it doesn't select the row.
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
        <span
          className="inline-flex"
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          <Switch
            label={`Enable ${row.name}`}
            hideLabel
            checked={row.enabled}
            disabled={!canWrite}
            onCheckedChange={(next) => {
              toggle(row, next);
            }}
          />
        </span>
      ),
    },
  ];

  const newButton = (
    <Button
      variant="primary"
      size="32"
      disabled={!canWrite}
      onClick={() => {
        setForm({ mode: "new" });
      }}
    >
      <Plus aria-hidden />
      New schedule
    </Button>
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-y-auto px-6 pt-5 pb-10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex max-w-3xl flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[22px] font-semibold tracking-tight">Scheduler</h1>
            <StatusLine
              running={status.data ? status.data.running : undefined}
              interval={status.data?.poll_interval_seconds ?? null}
            />
          </div>
          <p className="text-[13px] text-fg-secondary">
            Cron schedules that call your AgentOS endpoints as background runs. Times are shown in each
            schedule&apos;s own timezone.
          </p>
        </div>
        {canWrite ? (
          newButton
        ) : (
          <Tooltip content="Needs schedules:write">
            <span title="Needs schedules:write" className="inline-flex">
              {newButton}
            </span>
          </Tooltip>
        )}
      </div>

      {failing.map((schedule) => (
        <FailureBanner key={schedule.id} instance={instance} schedule={schedule} />
      ))}

      {schedules.isError ? (
        <ErrorState {...describeError(schedules.error)} onRetry={() => void schedules.refetch()} />
      ) : schedules.isPending ? (
        <LoadingRows label="Loading schedules" />
      ) : rows.length === 0 ? (
        <EmptyState title="No schedules yet.">
          A schedule starts a background run of an agent, team or workflow on a cron, in its own timezone.
        </EmptyState>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <div className="flex min-w-0 flex-[3_1_600px] flex-col gap-2 overflow-x-auto">
            <div className="min-w-[600px]">
              <DataTable
                label="Schedules"
                columns={columns}
                rows={rows}
                rowKey={(row) => row.id}
                selectedKey={selected?.id}
                onRowClick={(row) => {
                  go({ schedule: row.id });
                }}
                footer={
                  <span className="mr-auto font-mono text-[11.5px]">
                    GET /schedules · {formatCount(total)} schedule{total === 1 ? "" : "s"} · enable and
                    disable need schedules:write
                  </span>
                }
              />
            </div>
          </div>
          {selected && (
            <ScheduleDetail
              key={selected.id}
              instance={instance}
              schedule={selected}
              canWrite={canWrite}
              canDelete={canDelete}
              onEdit={() => {
                setForm({ mode: "edit", schedule: selected });
              }}
              onToggle={(enabled) => {
                toggle(selected, enabled);
              }}
              onDeleted={() => {
                go({ schedule: undefined });
              }}
            />
          )}
        </div>
      )}

      <DisableDialog
        schedule={disabling}
        onCancel={() => {
          setDisabling(undefined);
        }}
        onConfirm={(schedule, reason) => {
          setDisabling(undefined);
          setEnabled(schedule, false, reason);
        }}
      />
      {form && (
        <ScheduleFormDialog
          instance={instance}
          schedule={form.mode === "edit" ? form.schedule : undefined}
          canCustom={canCustom}
          onClose={() => {
            setForm(undefined);
          }}
          onSaved={(saved) => {
            setForm(undefined);
            go({ schedule: saved.id });
          }}
        />
      )}
    </div>
  );
}
