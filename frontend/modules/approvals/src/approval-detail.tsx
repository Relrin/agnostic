// The approval aside: who asked and why, the tool arguments (editable before approving, with the diff the audit log
// records), the decision, and the timeline of routing, views and resolution.
import {
  approvalsDecideMutation,
  approvalsGetApprovalOptions,
  describeError,
  type ApprovalDetailOut,
  type DecideOut,
} from "@agnostic/api";
import { formatWhen, toDate, useMe, withQueryFn } from "@agnostic/core";
import {
  ArgsDiff,
  Badge,
  Button,
  Callout,
  Countdown,
  EntitySquare,
  ErrorState,
  Input,
  JsonView,
  LoadingRows,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusPill,
  Textarea,
  Timeline,
  cn,
  formatCountdown,
  toast,
  type TimelineItem,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Bot, Pencil, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  argText,
  formatAge,
  outcomeText,
  parseArg,
  refreshApprovals,
  sourceName,
  userLabel,
} from "./approvals-api";

const ASIDE =
  "flex w-[460px] max-w-full shrink-0 flex-col gap-5 overflow-y-auto border-l border-border-subtle p-5";

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2">
        <h3 id={id} className="text-[13px] font-semibold">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function StatusBadge({ detail }: { detail: ApprovalDetailOut }) {
  if (detail.status === "pending")
    return <Badge tone="warning">{detail.type === "audit" ? "PENDING" : "RUN PAUSED"}</Badge>;
  return <StatusPill status={detail.status} />;
}

function SourceSquare({ kind }: { kind: string | null }) {
  if (kind === "agent" || kind === "team" || kind === "workflow") return <EntitySquare kind={kind} />;
  return <span aria-hidden className="inline-block size-2.5 shrink-0 rounded-type bg-fg-muted" />;
}

/** The edit form: one row per argument (110px mono label | input); numbers stay numbers. */
function ArgsForm({
  args,
  texts,
  invalid,
  onChange,
}: {
  args: Record<string, unknown>;
  texts: Record<string, string>;
  invalid: readonly string[];
  onChange: (key: string, text: string) => void;
}) {
  const prefix = useId();
  return (
    <div className="grid grid-cols-[110px_1fr] items-center gap-x-3 gap-y-2">
      {Object.entries(args).map(([key, original]) => {
        const id = `${prefix}-${key}`;
        const text = texts[key] ?? argText(original);
        const changed = text !== argText(original);
        const bad = invalid.includes(key);
        return (
          <div key={key} className="contents">
            <label htmlFor={id} className="truncate font-mono text-[12px] text-fg-muted">
              {key}
            </label>
            {typeof original === "boolean" ? (
              <Select
                value={text}
                onValueChange={(value) => {
                  onChange(key, value);
                }}
              >
                <SelectTrigger
                  id={id}
                  className={cn("h-8 font-mono text-[12.5px]", changed && "border-accent")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">true</SelectItem>
                  <SelectItem value="false">false</SelectItem>
                </SelectContent>
              </Select>
            ) : (
              <Input
                id={id}
                mono
                type={typeof original === "number" ? "number" : "text"}
                step={typeof original === "number" ? "any" : undefined}
                aria-invalid={bad || undefined}
                className={cn("h-8", changed && !bad && "border-accent")}
                value={text}
                onChange={(event) => {
                  onChange(key, event.target.value);
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function resolutionTitle(detail: ApprovalDetailOut): string {
  const who = detail.resolved_by_name ?? detail.resolved_by ?? "someone";
  switch (detail.status) {
    case "approved":
      return detail.type === "audit" ? `Confirmed by ${who} · audit record` : `Approved by ${who}`;
    case "rejected":
      return `Rejected by ${who}`;
    case "expired":
      return "Expired without a decision";
    case "cancelled":
      return "Cancelled";
    default:
      return "";
  }
}

function Resolution({ detail }: { detail: ApprovalDetailOut }) {
  const changed = detail.args_changed;
  const when = detail.resolved_at ? formatWhen(detail.resolved_at) : undefined;
  let body: ReactNode;
  if (detail.status === "expired") {
    body = detail.expiry_enforced ? (
      <>
        The run was cancelled at <code className="font-mono">expires_at</code>. Consider routing{" "}
        {sourceName(detail)} approvals to a second group.
      </>
    ) : (
      "Expired · the run stays paused until someone continues it from the instance."
    );
  } else if (detail.status === "cancelled") {
    body = "The run was cancelled before anyone decided.";
  } else {
    body = (
      <>
        {detail.note && <span className="block text-fg">“{detail.note}”</span>}
        {detail.type === "audit"
          ? "Audit approvals never block; this record was written after the confirmation step."
          : changed.length
            ? `Edited ${changed.join(", ")} before approving.`
            : "No argument changes."}
        {detail.run_status && detail.status === "approved" && detail.type !== "audit"
          ? ` Run status: ${detail.run_status}.`
          : ""}
      </>
    );
  }
  return (
    <div
      role="group"
      aria-label="Resolution"
      className={cn(
        "flex flex-col gap-1 rounded-tile border px-3.5 py-3 text-[12.5px] text-fg-secondary",
        detail.status === "rejected" ? "border-danger/30" : "border-border",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold text-fg">{resolutionTitle(detail)}</span>
        {when && <span className="text-[12px] text-fg-muted">{when}</span>}
      </div>
      <p>{body}</p>
      {changed.length > 0 && detail.status === "approved" && (
        <ArgsDiff before={detail.tool_args} after={{ ...detail.tool_args, ...detail.resolution_data }} />
      )}
    </div>
  );
}

function ResolveForm({
  instance,
  detail,
  edited,
  argsInvalid,
  intent,
  onDecided,
}: {
  instance: string;
  detail: ApprovalDetailOut;
  /** The edited arguments, when they differ from the original. */
  edited: Record<string, unknown> | undefined;
  argsInvalid: boolean;
  intent: "approve" | "reject" | undefined;
  onDecided: (result: DecideOut) => void;
}) {
  const client = useQueryClient();
  const me = useMe();
  const [note, setNote] = useState("");
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const approveRef = useRef<HTMLButtonElement>(null);
  const sectionRef = useRef<HTMLDivElement>(null);
  const decide = useMutation({
    ...approvalsDecideMutation(),
    onSuccess: async (data) => {
      onDecided(data);
      await refreshApprovals(client);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  // A Slack deep link lands here with the decision preselected: bring it into view, never submit it.
  useEffect(() => {
    if (!intent) return;
    sectionRef.current?.scrollIntoView({ block: "center" });
    (intent === "reject" ? noteRef.current : approveRef.current)?.focus();
  }, [intent]);

  const trimmed = note.trim();
  const send = (decision: "approve" | "reject") => {
    decide.mutate({
      path: { instance, approval_id: detail.id },
      body: {
        decision,
        ...(trimmed ? { note: trimmed } : {}),
        ...(decision === "approve" && edited ? { edited_args: edited } : {}),
      },
    });
  };

  return (
    <div ref={sectionRef} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${detail.id}-note`} className="text-[12.5px] font-medium text-fg-secondary">
          Note · required to reject
        </label>
        <Textarea
          id={`${detail.id}-note`}
          ref={noteRef}
          className="min-h-20 font-sans text-[13px]"
          placeholder="Visible to the requester and in the audit log"
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
      </div>
      <div className="flex gap-2">
        <Button
          variant="destructive-outline"
          size="36"
          className={cn("flex-1", intent === "reject" && "ring-2 ring-danger/50")}
          disabled={!trimmed || decide.isPending}
          onClick={() => {
            send("reject");
          }}
        >
          Reject
        </Button>
        <Button
          ref={approveRef}
          variant="primary"
          size="36"
          className={cn(
            "flex-[2]",
            intent === "approve" && "ring-2 ring-accent/50 ring-offset-2 ring-offset-rail",
          )}
          disabled={decide.isPending || argsInvalid}
          onClick={() => {
            send("approve");
          }}
        >
          Approve &amp; continue run
        </Button>
      </div>
      <p className="text-[12px] text-fg-muted">
        You resolve as {me.data?.display_name ?? "yourself"}. User-isolated callers and scoped service
        accounts can&apos;t resolve; the API answers 404 even with{" "}
        <code className="font-mono">approvals:write</code>.
      </p>
    </div>
  );
}

function timelineItems(detail: ApprovalDetailOut): TimelineItem[] {
  return detail.timeline.map((entry, index) => {
    const at = entry.at ? formatWhen(entry.at) : undefined;
    const meta = [at, entry.detail].filter(Boolean).join(" · ");
    return { key: String(index), text: entry.text, state: entry.state, ...(meta ? { meta } : {}) };
  });
}

function DetailBody({
  instance,
  detail,
  intent,
  onClose,
}: {
  instance: string;
  detail: ApprovalDetailOut;
  intent: "approve" | "reject" | undefined;
  onClose: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [outcome, setOutcome] = useState<DecideOut | undefined>();
  const [texts, setTexts] = useState<Record<string, string>>({});
  const args = detail.tool_args;
  const parsed = Object.entries(args).map(([key, original]) => {
    const text = texts[key];
    return [key, text === undefined ? { value: original } : parseArg(original, text)] as const;
  });
  const invalid = parsed.filter(([, result]) => result === undefined).map(([key]) => key);
  const edited = Object.fromEntries(parsed.map(([key, result]) => [key, result ? result.value : args[key]]));
  const changed = Object.keys(args).some((key) => JSON.stringify(args[key]) !== JSON.stringify(edited[key]));
  const pending = detail.status === "pending";
  const canEdit = pending && detail.can_resolve && Object.keys(args).length > 0;
  const expires = toDate(detail.expires_at);
  const encoded = encodeURIComponent(instance);
  const user = userLabel(detail);
  const context = detail.context;

  return (
    <>
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="outline">{detail.type.toUpperCase()}</Badge>
            <StatusBadge detail={detail} />
            {pending && expires && (
              <span className="text-[12px] text-fg-muted">
                expires <Countdown target={expires} />
              </span>
            )}
            {detail.status === "expired" && expires && (
              <span className="text-[12px] text-fg-muted">expired {formatCountdown(expires)}</span>
            )}
          </div>
          <Button variant="icon" size="28" aria-label="Close approval" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>
        <h2 className="font-mono text-[17px] font-semibold break-all">{detail.tool_name ?? detail.id}</h2>
        <p className="flex flex-wrap items-center gap-x-1 text-[12.5px] text-fg-secondary">
          <SourceSquare kind={detail.source_kind} />
          {detail.source_kind ?? "source"}{" "}
          <strong className="font-medium text-fg">{sourceName(detail)}</strong>
          {" · "}requested {formatAge(detail.created_at)} ago by{" "}
          <code className="font-mono text-fg">{user}</code>
          {detail.via && <> via {detail.via}</>}
        </p>
        <div className="flex flex-wrap gap-3 text-[12.5px]">
          {detail.session_id && (
            <Link
              to={`/i/${encoded}/sessions/${encodeURIComponent(detail.session_id)}`}
              className="inline-flex items-center gap-1 text-info hover:text-info-hover"
            >
              Open session <code className="font-mono">{detail.session_id}</code>
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          )}
          {detail.run_id && (
            <Link
              to={`/i/${encoded}/traces`}
              search={{ run_id: detail.run_id }}
              className="inline-flex items-center gap-1 text-info hover:text-info-hover"
            >
              View trace
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          )}
        </div>
      </header>

      {(context.user_message ?? context.agent_message) && (
        <Section title="Context">
          {context.user_message && (
            <div className="rounded-[10px] bg-bubble-user px-3.5 py-2.5 text-[13px] whitespace-pre-wrap">
              {context.user_message}
            </div>
          )}
          {context.agent_message && (
            <div className="flex gap-2.5 rounded-[10px] border border-border px-3.5 py-2.5 text-[13px] whitespace-pre-wrap">
              <Bot className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
              <span>{context.agent_message}</span>
            </div>
          )}
        </Section>
      )}

      <Section
        title="Tool arguments"
        action={
          canEdit ? (
            <Button
              variant="ghost"
              size="28"
              aria-pressed={editing}
              onClick={() => {
                setEditing(!editing);
              }}
            >
              <Pencil aria-hidden />
              {editing ? "Done editing" : "Edit before approving"}
            </Button>
          ) : undefined
        }
      >
        {editing ? (
          <>
            <ArgsForm
              args={args}
              texts={texts}
              invalid={invalid}
              onChange={(key, text) => {
                setTexts((current) => ({ ...current, [key]: text }));
              }}
            />
            {invalid.length > 0 && (
              <p role="alert" className="text-[12px] text-danger">
                {invalid.join(", ")} {invalid.length === 1 ? "doesn't" : "don't"} parse as the original type.
              </p>
            )}
            <ArgsDiff before={args} after={edited} />
            <p className="text-[12px] text-fg-muted">
              Changed values go out as <code className="font-mono">resolution_data</code> and show in the
              audit log as a before/after diff.
            </p>
          </>
        ) : changed ? (
          <>
            <JsonView value={edited} label="Tool arguments" />
            <ArgsDiff before={args} after={edited} />
          </>
        ) : Object.keys(args).length > 0 ? (
          <JsonView value={args} label="Tool arguments" />
        ) : (
          <p className="text-[12.5px] text-fg-muted">The tool was called without arguments.</p>
        )}
      </Section>

      {outcome && (
        <p role="status" className="rounded-tile border border-accent/30 px-3.5 py-3 text-[13px]">
          {outcomeText(outcome)}
        </p>
      )}
      {pending && !outcome && (
        <Section title="Resolve">
          {detail.can_resolve ? (
            <ResolveForm
              instance={instance}
              detail={detail}
              edited={changed ? edited : undefined}
              argsInvalid={invalid.length > 0}
              intent={intent}
              onDecided={setOutcome}
            />
          ) : (
            <Callout tone="info" title="You can't resolve this one">
              {detail.cannot_resolve_reason ?? "Resolving needs approvals:write on this instance."}
            </Callout>
          )}
        </Section>
      )}
      {!pending && <Resolution detail={detail} />}

      {(detail.routed_to.length > 0 || detail.views.length > 0) && (
        <p className="text-[12px] text-fg-muted">
          {detail.routed_to.length > 0 && <>Routed to {detail.routed_to.join(" and ")}. </>}
          {detail.views.length > 0 && (
            <>Viewed by {[...new Set(detail.views.map((view) => view.name))].join(", ")}.</>
          )}
        </p>
      )}

      {detail.timeline.length > 0 && (
        <Section title="Timeline">
          <Timeline label="Approval timeline" items={timelineItems(detail)} />
        </Section>
      )}
    </>
  );
}

/** `GET /approvals/{id}` (which records that you viewed it), then the detail. */
export function ApprovalDetail({
  instance,
  approvalId,
  intent,
  onClose,
}: {
  instance: string;
  approvalId: string;
  intent: "approve" | "reject" | undefined;
  onClose: () => void;
}) {
  const detail = useQuery(
    withQueryFn(approvalsGetApprovalOptions({ path: { instance, approval_id: approvalId } })),
  );
  return (
    <aside aria-label="Approval details" aria-busy={detail.isPending} className={ASIDE}>
      {detail.isPending ? (
        <LoadingRows rows={6} label="Loading approval" />
      ) : detail.isError ? (
        <>
          <div className="flex justify-end">
            <Button variant="icon" size="28" aria-label="Close approval" onClick={onClose}>
              <X aria-hidden />
            </Button>
          </div>
          <ErrorState {...describeError(detail.error)} onRetry={() => void detail.refetch()} />
        </>
      ) : (
        <DetailBody instance={instance} detail={detail.data} intent={intent} onClose={onClose} />
      )}
    </aside>
  );
}
