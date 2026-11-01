// Run widgets (04 §3.3): EntitySquare, ToolCallChip, RunBlock, UserBubble, ApprovalCard, StepTimeline, StepHitlForm,
// RunTimelineSeparator, RunCard. Presentational: pages map RunState to these props.
import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  LoaderCircle,
  Pause,
  Repeat,
  Split,
  TriangleAlert,
  Wrench,
  X,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { StatusPill } from "../primitives/badge";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";

export type EntityKind = "agent" | "team" | "workflow";

const ENTITY_COLOR: Record<EntityKind, string> = {
  agent: "bg-entity-agent",
  team: "bg-entity-team",
  workflow: "bg-entity-workflow",
};

export function EntitySquare({ kind, className }: { kind: EntityKind; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2.5 shrink-0 rounded-type", ENTITY_COLOR[kind], className)}
    />
  );
}

export type ToolChipStatus = "running" | "done" | "error" | "paused" | "awaiting";

export function ToolCallChip({
  name,
  status,
  duration,
}: {
  name: string;
  status: ToolChipStatus;
  /** "0.4s". */
  duration?: string | undefined;
}) {
  const icon =
    status === "running" ? (
      <LoaderCircle className="size-3 animate-spin" aria-hidden />
    ) : status === "done" ? (
      <Check className="size-3 text-accent" aria-hidden />
    ) : status === "error" ? (
      <X className="size-3 text-danger" aria-hidden />
    ) : (
      <Pause className="size-3 text-warning" aria-hidden />
    );
  const suffix =
    status === "paused"
      ? "paused"
      : status === "awaiting"
        ? "awaiting approval"
        : status === "error"
          ? "failed"
          : duration;
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-control border px-2 font-mono text-[11.5px]",
        status === "paused" || status === "awaiting"
          ? "border-warning/40 bg-warning-pill-bg text-warning-pill-fg"
          : status === "error"
            ? "border-danger/40 text-danger"
            : "border-border-strong text-fg-secondary",
      )}
    >
      {icon}
      {name}
      {suffix && <span className="text-fg-muted">{suffix}</span>}
    </span>
  );
}

export function UserBubble({ children, attachments }: { children: ReactNode; attachments?: ReactNode }) {
  return (
    <div className="flex justify-end">
      <div className="flex max-w-[78%] flex-col gap-1.5 rounded-card bg-bubble-user px-3.5 py-2.5 text-[14px] whitespace-pre-wrap text-fg">
        {children}
        {attachments}
      </div>
    </div>
  );
}

/** One run in a conversation: header (glyph, name, version, "worked 3.1 s", status), tool chips, body, toolbar. */
export function RunBlock({
  label,
  kind,
  name,
  version,
  worked,
  status,
  tools,
  children,
  toolbar,
  streaming = false,
}: {
  /** "Run run_9f2c41". */
  label: string;
  kind: EntityKind;
  name: string;
  version?: string | undefined;
  worked?: string | undefined;
  status: string;
  tools?: ReactNode;
  children?: ReactNode;
  toolbar?: ReactNode;
  streaming?: boolean;
}) {
  return (
    <article aria-label={label} aria-busy={streaming} className="flex flex-col gap-2.5">
      <header className="flex flex-wrap items-center gap-2 text-[13px]">
        <EntitySquare kind={kind} />
        <span className="font-semibold">{name}</span>
        {version && <span className="font-mono text-[12px] text-fg-muted">{version}</span>}
        {worked && (
          <>
            <span className="text-fg-faint">·</span>
            <span className="text-fg-muted">{worked}</span>
          </>
        )}
        <StatusPill status={status} />
      </header>
      {tools && <div className="flex flex-wrap gap-1.5">{tools}</div>}
      {children}
      {streaming && <span aria-hidden className="inline-block h-4 w-1.5 animate-pulse bg-fg-muted" />}
      {toolbar}
    </article>
  );
}

export function RunToolbar({ children, meta }: { children: ReactNode; meta?: ReactNode }) {
  return (
    <div role="toolbar" aria-label="Run actions" className="flex flex-wrap items-center gap-1">
      {children}
      {meta && <span className="ml-auto font-mono text-[11.5px] text-fg-muted">{meta}</span>}
    </div>
  );
}

/** Inline approval for a paused tool call: approve, reject, or edit the arguments first. */
export function ApprovalCard({
  toolName,
  args,
  requested,
  onApprove,
  onReject,
  busy = false,
  canDecide,
  cannotDecideReason,
  footer,
  outcome,
}: {
  toolName: string;
  args: Record<string, unknown>;
  /** "requested 2 min ago". */
  requested?: string | undefined;
  onApprove: (editedArgs: Record<string, unknown> | undefined) => void;
  onReject: () => void;
  busy?: boolean;
  canDecide: boolean;
  cannotDecideReason?: string | undefined;
  /** "Shown because you hold approvals:write on prod-agentos". */
  footer?: ReactNode;
  /** After a decision: "Approved by you · run continuing". */
  outcome?: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => JSON.stringify(args, null, 2));
  const [error, setError] = useState<string | undefined>();
  const editorId = useId();

  const approve = () => {
    if (!editing) {
      onApprove(undefined);
      return;
    }
    try {
      const parsed = JSON.parse(draft) as unknown;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setError("The arguments must be a JSON object.");
        return;
      }
      setError(undefined);
      onApprove(parsed as Record<string, unknown>);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Not valid JSON.");
    }
  };

  return (
    <section
      aria-label={`Approval required for ${toolName}`}
      className="flex flex-col gap-3 rounded-tile border border-warning/40 bg-warning/5 px-4 py-3.5"
    >
      <header className="flex flex-wrap items-center gap-2 text-[13px]">
        <TriangleAlert className="size-4 text-warning" aria-hidden />
        <span className="font-semibold">Approval required</span>
        <code className="rounded-type bg-surface-hover px-1 font-mono text-[12px]">{toolName}</code>
        {requested && <span className="text-[12px] text-fg-muted">blocking · {requested}</span>}
      </header>
      {editing ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={editorId} className="text-[12px] text-fg-muted">
            tool_args (JSON)
          </label>
          <textarea
            id={editorId}
            value={draft}
            spellCheck={false}
            aria-invalid={error !== undefined}
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            className="min-h-32 rounded-control border border-border-input bg-inset px-3 py-2 font-mono text-[12px] text-fg focus-visible:outline-2 focus-visible:outline-accent"
          />
          {error && <p className="text-[12px] text-danger">{error}</p>}
        </div>
      ) : (
        <pre
          aria-label="tool_args"
          className="overflow-x-auto rounded-control border border-border bg-inset px-3 py-2 font-mono text-[12px] text-fg"
        >
          {JSON.stringify(args, null, 2)}
        </pre>
      )}
      {outcome ? (
        <p className="text-[12.5px] text-fg-secondary">{outcome}</p>
      ) : canDecide ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" size="30" disabled={busy} onClick={approve}>
            {editing ? "Approve with edits" : "Approve"}
          </Button>
          <Button variant="outline" size="30" disabled={busy} onClick={onReject}>
            Reject
          </Button>
          <Button
            variant="ghost"
            size="30"
            disabled={busy}
            aria-pressed={editing}
            onClick={() => {
              setEditing(!editing);
              setError(undefined);
              setDraft(JSON.stringify(args, null, 2));
            }}
          >
            {editing ? "Cancel edit" : "Edit args"}
          </Button>
        </div>
      ) : (
        <p className="text-[12.5px] text-fg-secondary">{cannotDecideReason}</p>
      )}
      {footer && <footer className="text-[12px] text-fg-muted">{footer}</footer>}
    </section>
  );
}

export type StepView = {
  id: string;
  name: string;
  kind: "step" | "loop" | "router" | "parallel" | "condition" | "steps";
  status: string;
  detail?: string | undefined;
  children: StepView[];
};

const STEP_ICON = {
  step: CircleDashed,
  loop: Repeat,
  router: Split,
  parallel: Split,
  condition: Split,
  steps: Wrench,
} as const;

function StepRow({ step, depth }: { step: StepView; depth: number }) {
  const [open, setOpen] = useState(true);
  const Icon = STEP_ICON[step.kind];
  const hasChildren = step.children.length > 0;
  return (
    <li className="flex flex-col">
      <div className="flex items-center gap-2 py-1 text-[12.5px]" style={{ paddingLeft: depth * 16 }}>
        {hasChildren ? (
          <button
            type="button"
            className="cursor-pointer text-fg-muted hover:text-fg"
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${step.name}`}
            onClick={() => {
              setOpen(!open);
            }}
          >
            {open ? (
              <ChevronDown className="size-3.5" aria-hidden />
            ) : (
              <ChevronRight className="size-3.5" aria-hidden />
            )}
          </button>
        ) : (
          <span className="w-3.5" />
        )}
        <Icon className="size-3.5 text-fg-muted" aria-hidden />
        <span className="font-medium">{step.name}</span>
        {step.detail && <span className="text-fg-muted">{step.detail}</span>}
        <StatusPill status={step.status} className="ml-auto" />
      </div>
      {hasChildren && open && (
        <ul>
          {step.children.map((child) => (
            <StepRow key={child.id} step={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Collapsible workflow step progress (steps, loops with iterations, routers with the chosen route). */
export function StepTimeline({
  steps,
  label = "Workflow steps",
}: {
  steps: readonly StepView[];
  label?: string;
}) {
  if (steps.length === 0) return null;
  return (
    <ul aria-label={label} className="flex flex-col rounded-tile border border-border bg-surface px-3 py-1.5">
      {steps.map((step) => (
        <StepRow key={step.id} step={step} depth={0} />
      ))}
    </ul>
  );
}

export type HitlField = {
  name: string;
  type: string;
  description?: string | undefined;
  required: boolean;
  allowedValues?: readonly string[] | undefined;
};

export type HitlRequest = {
  stepName: string;
  confirmation?: string | undefined;
  userInput?: { message?: string | undefined; fields: readonly HitlField[] } | undefined;
  routes?: { choices: readonly string[]; multiple: boolean } | undefined;
  outputReview?: string | undefined;
};

export type HitlResolution = {
  confirmed: boolean;
  userInput?: Record<string, unknown> | undefined;
  selected?: string[] | undefined;
};

function coerce(type: string, raw: string): unknown {
  if (type === "int") return Number.parseInt(raw, 10);
  if (type === "float") return Number.parseFloat(raw);
  if (type === "bool") return raw === "true";
  if (type === "list" || type === "dict") {
    try {
      return JSON.parse(raw) as unknown;
    } catch {
      return raw;
    }
  }
  return raw;
}

/** Workflow step HITL: confirm, fill the user-input form (from `user_input_schema`), pick a route, review output. */
export function StepHitlForm({
  request,
  onSubmit,
  busy = false,
  disabledReason,
}: {
  request: HitlRequest;
  onSubmit: (resolution: HitlResolution) => void;
  busy?: boolean;
  disabledReason?: string | undefined;
}) {
  const formId = useId();
  const [values, setValues] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string[]>([]);

  const submit = (confirmed: boolean) => {
    const userInput = request.userInput
      ? Object.fromEntries(
          request.userInput.fields
            .filter((field) => values[field.name] !== undefined && values[field.name] !== "")
            .map((field) => [field.name, coerce(field.type, values[field.name] ?? "")]),
        )
      : undefined;
    onSubmit({ confirmed, userInput, selected: request.routes ? selected : undefined });
  };
  const missing =
    request.userInput?.fields.some((field) => field.required && !values[field.name]) === true ||
    (request.routes !== undefined && selected.length === 0);

  return (
    <section
      aria-label={`Input needed for ${request.stepName}`}
      className="flex flex-col gap-3 rounded-tile border border-warning/40 bg-warning/5 px-4 py-3.5"
    >
      <header className="flex items-center gap-2 text-[13px]">
        <Pause className="size-4 text-warning" aria-hidden />
        <span className="font-semibold">Step {request.stepName} is waiting</span>
      </header>
      {request.confirmation && <p className="text-[13px] text-fg-secondary">{request.confirmation}</p>}
      {request.outputReview && (
        <pre className="max-h-48 overflow-auto rounded-control border border-border bg-inset px-3 py-2 font-mono text-[12px] whitespace-pre-wrap">
          {request.outputReview}
        </pre>
      )}
      {request.userInput && (
        <form
          id={formId}
          className="flex flex-col gap-2.5"
          onSubmit={(event) => {
            event.preventDefault();
            submit(true);
          }}
        >
          {request.userInput.message && (
            <p className="text-[13px] text-fg-secondary">{request.userInput.message}</p>
          )}
          {request.userInput.fields.map((field) => {
            const id = `${formId}-${field.name}`;
            return (
              <div key={field.name} className="flex flex-col gap-1">
                <label htmlFor={id} className="text-[12.5px] font-medium">
                  {field.name}
                  {field.required && <span className="text-danger"> *</span>}
                  <span className="ml-1.5 font-mono text-[11px] text-fg-muted">{field.type}</span>
                </label>
                {field.allowedValues && field.allowedValues.length > 0 ? (
                  <select
                    id={id}
                    value={values[field.name] ?? ""}
                    onChange={(event) => {
                      setValues({ ...values, [field.name]: event.target.value });
                    }}
                    className="h-8 rounded-control border border-border-input bg-surface px-2 text-[13px]"
                  >
                    <option value="">Choose…</option>
                    {field.allowedValues.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                ) : field.type === "bool" ? (
                  <select
                    id={id}
                    value={values[field.name] ?? ""}
                    onChange={(event) => {
                      setValues({ ...values, [field.name]: event.target.value });
                    }}
                    className="h-8 rounded-control border border-border-input bg-surface px-2 text-[13px]"
                  >
                    <option value="">Choose…</option>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <Input
                    id={id}
                    mono={field.type !== "str"}
                    inputMode={field.type === "int" || field.type === "float" ? "decimal" : undefined}
                    value={values[field.name] ?? ""}
                    onChange={(event) => {
                      setValues({ ...values, [field.name]: event.target.value });
                    }}
                  />
                )}
                {field.description && <span className="text-[12px] text-fg-muted">{field.description}</span>}
              </div>
            );
          })}
        </form>
      )}
      {request.routes && (
        <fieldset className="flex flex-col gap-1.5">
          <legend className="pb-1 text-[12.5px] font-medium">Choose a route</legend>
          {request.routes.choices.map((choice) => (
            <label key={choice} className="flex items-center gap-2 text-[13px]">
              <input
                type={request.routes?.multiple ? "checkbox" : "radio"}
                name={`${formId}-route`}
                checked={selected.includes(choice)}
                onChange={(event) => {
                  if (request.routes?.multiple) {
                    setSelected(
                      event.target.checked
                        ? [...selected, choice]
                        : selected.filter((item) => item !== choice),
                    );
                  } else {
                    setSelected([choice]);
                  }
                }}
              />
              <span className="font-mono">{choice}</span>
            </label>
          ))}
        </fieldset>
      )}
      {disabledReason ? (
        <p className="text-[12.5px] text-fg-secondary">{disabledReason}</p>
      ) : (
        <div className="flex gap-2">
          <Button
            variant="primary"
            size="30"
            disabled={busy || missing}
            onClick={() => {
              submit(true);
            }}
          >
            {request.outputReview ? "Accept output" : request.userInput ? "Submit" : "Confirm"}
          </Button>
          <Button
            variant="outline"
            size="30"
            disabled={busy}
            onClick={() => {
              submit(false);
            }}
          >
            Reject
          </Button>
        </div>
      )}
    </section>
  );
}

/** "Run 2 · 10:44 · error" between runs of a session transcript. */
export function RunTimelineSeparator({ children }: { children: ReactNode }) {
  return (
    <div role="separator" className="flex items-center gap-3 py-1 text-[11.5px] text-fg-muted">
      <span className="h-px flex-1 bg-border-subtle" />
      <span className="font-mono">{children}</span>
      <span className="h-px flex-1 bg-border-subtle" />
    </div>
  );
}

/** One run in the Sessions "Runs" tab: status, meta, a sentence about what happened, and an action. */
export function RunCard({
  status,
  title,
  meta,
  note,
  action,
}: {
  status: string;
  title: ReactNode;
  meta: ReactNode;
  note?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <article className="flex flex-col gap-1.5 rounded-tile border border-border bg-surface px-4 py-3">
      <header className="flex items-center gap-2">
        <StatusPill status={status} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{title}</span>
        {action}
      </header>
      <div className="font-mono text-[11.5px] text-fg-muted">{meta}</div>
      {note && <p className="text-[12.5px] text-fg-secondary">{note}</p>}
    </article>
  );
}
