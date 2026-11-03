// The job aside: job status next to run status, the attempts narrative, the failure, checkpoints to resume from,
// and the recovery actions (resume, requeue with a forced retry on conflict, cancel).
import { describeError, type QueueJobDetailOut } from "@agnostic/api";
import { formatRelative } from "@agnostic/core";
import {
  ApiHint,
  Badge,
  Button,
  Callout,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorState,
  LoadingRows,
  RadioCards,
  Timeline,
  cn,
  toast,
  type BadgeProps,
  type TimelineItem,
} from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { FINISHED, isConflict, kindOf, useJobActions, useQueueJob, utcTime } from "./queue-api";

const JOB_TONE: Record<string, NonNullable<BadgeProps["tone"]>> = {
  queued: "muted",
  running: "info",
  paused: "warning",
  failed: "danger",
  completed: "success",
  cancelled: "muted",
};

/** Filled badges for the job's own status, so it reads apart from the run status next to it. */
const JOB_FILL: Record<string, string> = {
  failed: "bg-danger text-accent-fg",
  completed: "bg-accent text-accent-fg",
  paused: "bg-warning text-accent-fg",
  running: "bg-info text-accent-fg",
};

function Shell({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  return (
    <aside
      aria-label={label}
      className="relative flex w-[480px] shrink-0 flex-col gap-5 overflow-y-auto border-l border-border-subtle p-5"
    >
      <Button
        variant="icon"
        size="28"
        aria-label="Close job"
        className="absolute top-4 right-4"
        onClick={onClose}
      >
        <X aria-hidden />
      </Button>
      {children}
    </aside>
  );
}

function Heading({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h3 className="text-[13.5px] font-semibold">{children}</h3>
      {hint}
    </div>
  );
}

export function JobDetail({
  instance,
  jobId,
  onClose,
}: {
  instance: string;
  jobId: string;
  onClose: () => void;
}) {
  const detail = useQueueJob(instance, jobId);
  if (detail.isPending)
    return (
      <Shell label={`Job ${jobId}`} onClose={onClose}>
        <LoadingRows rows={6} label="Loading job" />
      </Shell>
    );
  if (detail.isError)
    return (
      <Shell label={`Job ${jobId}`} onClose={onClose}>
        <ErrorState {...describeError(detail.error)} onRetry={() => void detail.refetch()} />
      </Shell>
    );
  return <JobView instance={instance} job={detail.data} onClose={onClose} />;
}

function JobView({
  instance,
  job,
  onClose,
}: {
  instance: string;
  job: QueueJobDetailOut;
  onClose: () => void;
}) {
  const actions = useJobActions(instance, job.id);
  const [picked, setPicked] = useState<string | undefined>(undefined);
  const [conflict, setConflict] = useState<string | undefined>(undefined);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const kind = kindOf(job.component_type);
  const path = { instance, job_id: job.id };
  const status = job.status.toLowerCase();
  const inFlight = status === "queued" || status === "running";
  const latest = job.checkpoints.find((checkpoint) => checkpoint.is_latest) ?? job.checkpoints.at(-1);
  const selected = job.checkpoints.find((checkpoint) => String(checkpoint.number) === picked) ?? latest;
  const canResume = (kind === "agent" || kind === "team") && job.checkpoints.length > 0;
  const busy = actions.resume.isPending || actions.requeue.isPending || actions.cancel.isPending;
  const failure = [job.error, job.run_content].filter(
    (text, index, all): text is string => Boolean(text) && all.indexOf(text) === index,
  );
  const encoded = encodeURIComponent(instance);

  const attempts: TimelineItem[] = job.attempts.map((attempt, index) => ({
    key: String(index),
    text: attempt.text,
    meta: [utcTime(attempt.at), attempt.detail].filter(Boolean).join(" · ") || undefined,
    state: attempt.state,
  }));

  const fail = (error: unknown) => {
    toast.error(describeError(error).reason);
  };

  const resume = () => {
    if (!selected) return;
    actions.resume.mutate(
      { path, body: { message_index: selected.message_index } },
      {
        onSuccess: () => toast.success(`Resumed ${job.id} from checkpoint #${String(selected.number)}`),
        onError: fail,
      },
    );
  };

  const requeue = (force: boolean) => {
    actions.requeue.mutate(
      { path, body: force ? { force: true } : {} },
      {
        onSuccess: (next) => {
          setConflict(undefined);
          toast.success(
            `Requeued ${job.id}: attempt ${String(next.attempt + 1)} of ${String(next.max_attempts)} with the same run_id`,
          );
        },
        onError: (error) => {
          if (!force && isConflict(error)) setConflict(describeError(error).reason);
          else fail(error);
        },
      },
    );
  };

  const cancel = () => {
    actions.cancel.mutate(
      { path },
      {
        onSuccess: () => {
          setConfirmCancel(false);
          toast.success(`Cancelled ${job.id}`);
        },
        onError: fail,
      },
    );
  };

  return (
    <Shell label={status === "failed" ? `Failed job ${job.id}` : `Job ${job.id}`} onClose={onClose}>
      <header className="flex flex-col gap-2 pr-10">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={JOB_TONE[status] ?? "muted"} className={JOB_FILL[status]}>
            Job {status}
          </Badge>
          {job.run_status && <Badge tone="outline">Run {job.run_status}</Badge>}
        </div>
        <h2 className="font-mono text-[17px] font-semibold break-all">{job.run_id}</h2>
        <p className="text-[12.5px] text-fg-secondary">
          {kind ?? job.component_type ?? "run"}{" "}
          {job.component_id && <strong className="font-semibold text-fg">{job.component_id}</strong>}
          {job.user_id && (
            <>
              {" · user "}
              <code className="font-mono">{job.user_id}</code>
            </>
          )}
          {job.created_at && ` · accepted ${formatRelative(job.created_at)}`}
        </p>
        <div className="flex flex-wrap gap-3 text-[12.5px]">
          {job.session_id && (
            <Link
              to={`/i/${encoded}/sessions/${encodeURIComponent(job.session_id)}`}
              className="text-info hover:text-info-hover"
            >
              Open session
            </Link>
          )}
          <Link
            to={`/i/${encoded}/traces?run_id=${encodeURIComponent(job.run_id)}`}
            className="text-info hover:text-info-hover"
          >
            View trace
          </Link>
        </div>
      </header>

      <section aria-label="Attempts" className="flex flex-col gap-2.5">
        <Heading>Attempts</Heading>
        <Timeline label="Attempts" items={attempts} />
      </section>

      {failure.length > 0 && (
        <section className="flex flex-col gap-2">
          <Heading>{job.error ? "Failure reason · run content" : "Run content"}</Heading>
          <pre
            className={cn(
              "rounded-tile border px-3 py-2.5 font-mono text-[12px] break-words whitespace-pre-wrap",
              job.error
                ? "border-danger/30 bg-danger/5 text-[var(--danger-pre)]"
                : "border-border text-fg-secondary",
            )}
          >
            {failure.join("\n\n")}
          </pre>
        </section>
      )}

      {(kind === "agent" || kind === "team" || job.checkpoints_unavailable) && (
        <section aria-label="Checkpoints" className="flex flex-col gap-2.5">
          <Heading
            hint={
              kind !== "workflow" && (
                <ApiHint call={`GET …/runs/${job.run_id}/checkpoints`} scope="queue:operate">
                  <code className="font-mono text-[11.5px] text-fg-muted">
                    GET …/runs/{job.run_id}/checkpoints
                  </code>
                </ApiHint>
              )
            }
          >
            Checkpoints
          </Heading>
          {job.checkpoints_unavailable ? (
            <Callout tone="info">{job.checkpoints_unavailable}</Callout>
          ) : job.checkpoints.length === 0 ? (
            <p className="text-[12.5px] text-fg-muted">No checkpoints were saved for this run.</p>
          ) : (
            <>
              <RadioCards
                legend={<span className="sr-only">Checkpoint to resume from</span>}
                value={String(selected?.number ?? "")}
                onValueChange={setPicked}
                options={job.checkpoints.map((checkpoint) => ({
                  value: String(checkpoint.number),
                  label: `#${String(checkpoint.number)} ${checkpoint.title}`,
                  description: checkpoint.preview ?? undefined,
                }))}
              />
              <p className="text-[12px] text-fg-muted">
                Resuming from a checkpoint reuses saved tool results, so earlier tool calls are not made
                again.
              </p>
            </>
          )}
        </section>
      )}

      {conflict && (
        <Callout
          tone="warning"
          title="It failed moments ago"
          action={
            <Button
              size="30"
              variant="outline"
              disabled={busy}
              onClick={() => {
                requeue(true);
              }}
            >
              Requeue anyway
            </Button>
          }
        >
          {conflict} Its worker may still hold it until lock_grace_seconds pass; requeueing now can run it
          twice.
        </Callout>
      )}

      <footer className="mt-auto flex flex-col gap-2 border-t border-border-subtle pt-4">
        <div className="flex gap-2">
          {canResume && selected && (
            <Button
              variant="primary"
              size="32"
              className="flex-[2]"
              disabled={busy || inFlight}
              onClick={resume}
            >
              Resume from #{selected.number}
            </Button>
          )}
          <Button
            variant="outline"
            size="32"
            className="flex-1"
            disabled={busy || inFlight}
            onClick={() => {
              requeue(false);
            }}
          >
            Requeue
          </Button>
          <Dialog open={confirmCancel} onOpenChange={setConfirmCancel}>
            <Button
              variant="destructive-outline"
              size="32"
              className="flex-1"
              disabled={busy || FINISHED.includes(status)}
              onClick={() => {
                setConfirmCancel(true);
              }}
            >
              Cancel
            </Button>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Cancel {job.run_id}?</DialogTitle>
                <DialogDescription>
                  The run stops and the job is marked cancelled; it isn&apos;t retried. The action is audited.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="ghost" size="32">
                    Keep it
                  </Button>
                </DialogClose>
                <Button variant="destructive-outline" size="32" disabled={busy} onClick={cancel}>
                  Cancel job
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
        <p className="font-mono text-[11px] text-fg-muted">
          resume · cancel → run · requeue → POST /queue/jobs/{job.id}/requeue (+1 attempt)
        </p>
      </footer>
    </Shell>
  );
}
