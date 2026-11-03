// Building blocks shared by the organization settings sections.
import { useCan } from "@agnostic/core";
import { Button, Callout, Input } from "@agnostic/ui";
import { Check, Copy } from "lucide-react";
import { useState, type ReactNode } from "react";

export function Section({
  title,
  description,
  action,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4 rounded-card border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="text-[14.5px] font-semibold">{title}</h2>
          {description && <p className="text-[13px] text-fg-secondary">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Facts({ rows }: { rows: readonly (readonly [string, ReactNode])[] }) {
  return (
    <dl className="grid grid-cols-[minmax(140px,max-content)_1fr] gap-x-6 gap-y-2 text-[13px]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-fg-muted">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A read-only value with a copy button (URLs to paste into an identity provider). */
export function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <Input mono readOnly value={value} aria-label={label} />
      <Button
        size="34"
        variant="secondary"
        aria-label={`Copy ${label}`}
        onClick={() => {
          void navigator.clipboard.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => {
              setCopied(false);
            }, 1500);
          });
        }}
      >
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

/** Whether the signed-in person may change this section, and a note when not. */
export function useWritable(scope: string): { writable: boolean; note: ReactNode } {
  const can = useCan(scope);
  const writable = can.allowed === true;
  const note =
    can.allowed === false ? (
      <Callout tone="availability">Read only: changing this needs {scope}.</Callout>
    ) : null;
  return { writable, note };
}

/** "a, b , c" → ["a", "b", "c"]. */
export function splitList(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** An empty input means "not set". */
export function optionalNumber(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
