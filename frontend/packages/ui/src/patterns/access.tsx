// Access patterns: AccessChip (role + instance), ScopeDiff (token scopes added and removed), SaveBar (unsaved
// changes). Presentational only: pages pass names and scopes they already resolved.
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Button } from "../primitives/button";
import type { Environment } from "./page-header";

const ENV_DOT: Record<Environment, string> = {
  production: "bg-warning",
  staging: "bg-info",
  development: "bg-fg-muted",
};

/** `Operator · ● prod-agentos · via Support AI`: one binding as people see it. */
export function AccessChip({
  roleName,
  instance,
  env,
  via,
  color,
  expires,
  className,
}: {
  roleName: string;
  /** Instance slug; omitted for bindings on every instance ("all"). */
  instance?: string | null;
  env?: Environment | null;
  /** The group the binding comes from. */
  via?: string | null;
  /** The role's color (a hex value from the role editor). */
  color?: string | null;
  /** Already formatted ("ends 30 Nov"). */
  expires?: string | null;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-surface px-2 py-0.5 text-[12px]",
        className,
      )}
    >
      {color && (
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      )}
      <span className="truncate font-medium">{roleName}</span>
      <span aria-hidden className="text-fg-muted">
        ·
      </span>
      {instance ? (
        <span className="inline-flex items-center gap-1 font-mono text-[11.5px] text-fg-muted">
          {env && <span aria-hidden className={cn("size-1.5 rounded-full", ENV_DOT[env])} />}
          {instance}
        </span>
      ) : (
        <span className="font-mono text-[11.5px] text-fg-muted">all</span>
      )}
      {via && <span className="truncate text-[11.5px] text-fg-muted">via {via}</span>}
      {expires && <span className="text-[11.5px] text-warning">{expires}</span>}
    </span>
  );
}

export type DiffLine = { op: "add" | "remove" | "change" | "note"; text: string };

const SIGN: Record<DiffLine["op"], string> = { add: "+", remove: "−", change: "~", note: "·" };
const TONE: Record<DiffLine["op"], string> = {
  add: "text-accent",
  remove: "text-danger",
  change: "text-warning",
  note: "text-fg-muted",
};

/** `+ knowledge:write` / `− approvals:delete`: what a change does to token scopes (or any list of lines). */
export function ScopeDiff({
  lines,
  label = "Changes",
  empty = "No changes.",
  className,
}: {
  lines: DiffLine[];
  label?: string;
  empty?: ReactNode;
  className?: string;
}) {
  if (lines.length === 0) return <p className="text-[12px] text-fg-muted">{empty}</p>;
  return (
    <ul aria-label={label} className={cn("flex flex-col gap-0.5 font-mono text-[12px]", className)}>
      {lines.map((line, index) => (
        <li key={`${line.op}:${line.text}:${String(index)}`} className={cn("flex gap-2", TONE[line.op])}>
          <span aria-hidden className="w-3 shrink-0 text-center">
            {SIGN[line.op]}
          </span>
          <span className="sr-only">
            {line.op === "add" ? "Added" : line.op === "remove" ? "Removed" : ""}
          </span>
          <span className="break-all">{line.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Sticky footer of an editor: "{n} unsaved changes" (amber) or "All changes saved", with Discard and Save. */
export function SaveBar({
  dirty,
  saving = false,
  onSave,
  onDiscard,
  saveLabel = "Save changes",
  disabled = false,
  note,
  className,
}: {
  dirty: number;
  saving?: boolean;
  onSave: () => void;
  onDiscard: () => void;
  saveLabel?: string;
  disabled?: boolean;
  /** A short line next to the count ("No redeploy"). */
  note?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="region"
      aria-label="Save changes"
      className={cn(
        "sticky bottom-0 flex items-center gap-3 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur",
        className,
      )}
    >
      <span aria-live="polite" className={cn("text-[13px]", dirty > 0 ? "text-warning" : "text-fg-muted")}>
        {dirty > 0 ? `${String(dirty)} unsaved change${dirty === 1 ? "" : "s"}` : "All changes saved"}
      </span>
      {note && <span className="text-[12px] text-fg-muted">{note}</span>}
      <span className="flex-1" />
      <Button variant="ghost" size="32" disabled={dirty === 0 || saving} onClick={onDiscard}>
        Discard
      </Button>
      <Button variant="primary" size="32" disabled={dirty === 0 || saving || disabled} onClick={onSave}>
        {saving ? "Saving…" : saveLabel}
      </Button>
    </div>
  );
}
