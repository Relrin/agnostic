// The detail aside of a schedule: actions with the scopes they need, a note (failing, paused by a person, or
// disabled by AgentOS), "When it runs", the request it sends, and its run history.
import { describeError } from "@agnostic/api";
import { formatDuration, formatInZone, formatRelative } from "@agnostic/core";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  JsonView,
  KeyValueList,
  LoadingRows,
  StatusPill,
  cn,
  toast,
} from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import { Fragment, useState, type ReactNode } from "react";

import { DeleteDialog, ScopeHint } from "./schedule-actions";
import { usePreview, useScheduleActions, useScheduleRuns, type Schedule } from "./schedules-api";
import { CronReadout, RunPreview } from "./when-it-runs";

type Tone = "error" | "info" | "muted";

const NOTE_DOT: Record<Tone, string> = { error: "bg-danger", info: "bg-warning", muted: "bg-fg-muted" };

function Note({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <div
      data-tone={tone}
      className={cn(
        "flex items-start gap-2.5 rounded-tile border px-3 py-2.5 text-[12.5px]",
        tone === "error" && "border-danger/35 bg-danger/5",
        tone === "info" && "border-warning/35 bg-warning/6",
        tone === "muted" && "border-border bg-surface text-fg-secondary",
      )}
    >
      <span aria-hidden className={cn("mt-1.5 size-[7px] shrink-0 rounded-full", NOTE_DOT[tone])} />
      <p>{children}</p>
    </div>
  );
}

function Section({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  const id = `schedule-${title.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 border-t border-border-subtle pt-4">
      <header className="flex items-baseline justify-between gap-2">
        <h3 id={id} className="text-[13.5px] font-semibold">
          {title}
        </h3>
        {meta}
      </header>
      {children}
    </section>
  );
}

export function ScheduleDetail({
  instance,
  schedule,
  canWrite,
  canDelete,
  onEdit,
  onToggle,
  onDeleted,
}: {
  instance: string;
  schedule: Schedule;
  canWrite: boolean;
  canDelete: boolean;
  onEdit: () => void;
  onToggle: (enabled: boolean) => void;
  onDeleted: () => void;
}) {
  const actions = useScheduleActions(instance);
  const cron = schedule.cron_expr ?? "";
  const preview = usePreview(instance, cron, schedule.timezone);
  const runs = useScheduleRuns(instance, schedule.id);
  const [deleting, setDeleting] = useState(false);
  const id = encodeURIComponent(schedule.id);
  const failing = schedule.consecutive_failures;
  const lastError = schedule.last_runs.find((run) => run.error)?.error;

  return (
    <aside
      aria-label="Schedule details"
      className="flex w-full max-w-[480px] min-w-0 flex-[1_1_400px] flex-col gap-4 rounded-card border border-border bg-surface p-4"
    >
      <header className="flex flex-col gap-2.5">
        <div className="flex flex-col gap-1">
          <h2 className="font-mono text-[15px] font-semibold break-all">{schedule.name}</h2>
          {schedule.description && <p className="text-[13px] text-fg-secondary">{schedule.description}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ScopeHint allowed={canWrite} scope="schedules:write" call={`POST /schedules/${id}/trigger`}>
            <Button
              variant="primary"
              size="30"
              disabled={!canWrite || actions.trigger.isPending}
              onClick={() => {
                actions.trigger.mutate(schedule, {
                  onSuccess: () => toast.success(`Triggered ${schedule.name}`),
                  onError: (problem) => toast.error(describeError(problem).reason),
                });
              }}
            >
              ▶ Trigger now
            </Button>
          </ScopeHint>
          <ScopeHint allowed={canWrite} scope="schedules:write" call={`PATCH /schedules/${id}`}>
            <Button variant="outline" size="30" disabled={!canWrite} onClick={onEdit}>
              Edit
            </Button>
          </ScopeHint>
          <ScopeHint
            allowed={canWrite}
            scope="schedules:write"
            call={`POST /schedules/${id}/${schedule.enabled ? "disable" : "enable"}`}
          >
            <Button
              variant="outline"
              size="30"
              disabled={!canWrite}
              onClick={() => {
                onToggle(!schedule.enabled);
              }}
            >
              {schedule.enabled ? "Disable" : "Enable"}
            </Button>
          </ScopeHint>
          <ScopeHint allowed={canDelete} scope="schedules:delete" call={`DELETE /schedules/${id}`}>
            <Button
              variant="destructive-outline"
              size="30"
              disabled={!canDelete}
              onClick={() => {
                setDeleting(true);
              }}
            >
              Delete
            </Button>
          </ScopeHint>
        </div>
        <p className="font-mono text-[11px] text-fg-faint">
          trigger · edit · enable/disable → schedules:write · delete → schedules:delete
        </p>
      </header>

      {failing > 0 && (
        <Note tone="error">
          {failing === 1 ? "The last attempt failed" : `The last ${String(failing)} attempts failed`}
          {lastError ? `: ${lastError.replace(/\.$/, "")}.` : "."}{" "}
          {schedule.enabled && "Nobody has disabled it: the scheduler keeps it enabled until someone does."}
        </Note>
      )}
      {schedule.disabled_note && (
        <Note tone="muted">
          Paused by {schedule.disabled_note.by_name}: {schedule.disabled_note.reason}{" "}
          <span className="text-fg-muted">· {formatRelative(schedule.disabled_note.at)}</span>
        </Note>
      )}
      {schedule.disabled_reason && <Note tone="info">{schedule.disabled_reason}</Note>}

      <Section title="When it runs">
        {cron ? <CronReadout cron={cron} /> : null}
        <KeyValueList items={[{ key: "tz", label: "Timezone", value: schedule.timezone, mono: true }]} />
        <RunPreview preview={preview} cron={cron} />
      </Section>

      <Section title="Request">
        <KeyValueList
          items={[
            {
              key: "endpoint",
              label: "endpoint",
              mono: true,
              value: (
                <>
                  <span className="text-accent">{schedule.method}</span> {schedule.endpoint}
                </>
              ),
            },
            {
              key: "timeout",
              label: "timeout_seconds",
              mono: true,
              value: String(schedule.timeout_seconds ?? "—"),
            },
            { key: "retries", label: "max_retries", mono: true, value: String(schedule.max_retries) },
            {
              key: "delay",
              label: "retry_delay_seconds",
              mono: true,
              value: String(schedule.retry_delay_seconds ?? "—"),
            },
          ]}
        />
        <JsonView label="payload" value={schedule.payload ?? {}} />
      </Section>

      <Section
        title="Run history"
        meta={<code className="font-mono text-[11px] text-fg-muted">GET /schedules/{"{id}"}/runs</code>}
      >
        {runs.isError ? (
          <ErrorState {...describeError(runs.error)} onRetry={() => void runs.refetch()} />
        ) : runs.isPending ? (
          <LoadingRows rows={3} label="Loading runs" />
        ) : runs.data.data.length === 0 ? (
          <EmptyState title="No runs yet">
            {schedule.created_at ? `Created ${formatRelative(schedule.created_at)}.` : null}{" "}
            <Badge tone="muted">NO RUNS</Badge>
          </EmptyState>
        ) : (
          <ul aria-label="Runs" className="flex flex-col">
            {runs.data.data.map((run) => (
              <li
                key={run.id}
                className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-divider-row py-2 text-[12.5px] last:border-0"
              >
                <span className="flex min-w-0 flex-col">
                  <span>{formatInZone(run.triggered_at, schedule.timezone)}</span>
                  <span className="truncate text-[11.5px] text-fg-muted">{run.attempt_label}</span>
                </span>
                <span className="flex items-center gap-1">
                  {run.states.map((state, index) => (
                    <Fragment key={`${state}-${String(index)}`}>
                      {index > 0 && (
                        <span aria-hidden className="text-fg-muted">
                          →
                        </span>
                      )}
                      <StatusPill status={state} />
                    </Fragment>
                  ))}
                </span>
                <span className="flex min-w-[88px] flex-col items-end">
                  <span className="font-mono tabular-nums">
                    {run.duration_seconds === null ? "—" : formatDuration(run.duration_seconds * 1000)}
                  </span>
                  {run.run_id && (
                    <Link
                      to={`/i/${encodeURIComponent(instance)}/traces`}
                      search={{ run_id: run.run_id }}
                      className="text-[11.5px] text-info hover:text-info-hover"
                    >
                      Trace
                    </Link>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <DeleteDialog
        schedule={schedule}
        open={deleting}
        pending={actions.remove.isPending}
        onOpenChange={setDeleting}
        onConfirm={() => {
          actions.remove.mutate(schedule, {
            onSuccess: () => {
              setDeleting(false);
              toast.success(`Deleted ${schedule.name}`);
              onDeleted();
            },
            onError: (problem) => toast.error(describeError(problem).reason),
          });
        }}
      />
    </aside>
  );
}
