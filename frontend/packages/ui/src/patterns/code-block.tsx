// Monospace block with a copy button (config snippets, public keys), and step lists (wizards, diagnostics).
import { Check, CircleAlert, CircleCheck, CircleDashed, CircleX, Copy } from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "../lib/cn";

export function CodeBlock({
  title,
  code,
  className,
}: {
  title?: ReactNode;
  code: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 1500);
    });
  };
  return (
    <div
      className={cn("flex flex-col overflow-hidden rounded-tile border border-border bg-surface", className)}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border-subtle px-3 py-1.5">
        <span className="font-mono text-[11.5px] text-fg-muted">{title}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex cursor-pointer items-center gap-1 rounded-control px-1.5 py-0.5 text-[12px] text-fg-secondary hover:bg-surface-hover hover:text-fg"
        >
          {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-[12px] leading-relaxed whitespace-pre text-fg">
        {code}
      </pre>
    </div>
  );
}

export type StepState = "ok" | "failed" | "warning" | "skipped" | "pending";

const STEP_ICON = {
  ok: { icon: CircleCheck, className: "text-accent", label: "Passed" },
  failed: { icon: CircleX, className: "text-danger", label: "Failed" },
  warning: { icon: CircleAlert, className: "text-warning", label: "Warning" },
  skipped: { icon: CircleDashed, className: "text-fg-muted", label: "Skipped" },
  pending: { icon: CircleDashed, className: "text-fg-muted", label: "Not run" },
} as const;

/** Step-wise diagnostics: what passed, what failed, and what to do about it. */
export function StepList({
  steps,
}: {
  steps: readonly { id: string; label: string; status: StepState; detail?: string; hint?: string | null }[];
}) {
  return (
    <ol className="flex flex-col divide-y divide-divider-row rounded-card border border-border bg-surface">
      {steps.map((step) => {
        const style = STEP_ICON[step.status];
        const Icon = style.icon;
        return (
          <li key={step.id} className="flex gap-3 px-4 py-3">
            <Icon className={cn("mt-0.5 size-4 shrink-0", style.className)} aria-label={style.label} />
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-[13.5px] font-medium">{step.label}</span>
              {step.detail && (
                <span className="text-[13px] break-words text-fg-secondary">{step.detail}</span>
              )}
              {step.hint && <span className="text-[12.5px] text-info">{step.hint}</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
