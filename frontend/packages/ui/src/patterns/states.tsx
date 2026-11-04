// Empty, error and loading states: one sentence of purpose, one primary action, the request id on errors.
import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "../primitives/button";
import { Skeleton } from "../primitives/small";

export type DocsLink = {
  href: string;
  /** "Read the guide" by default. */
  label?: string;
};

export function EmptyState({
  title,
  children,
  action,
  docs,
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  /** A guide that explains the feature, opened in a new tab. */
  docs?: DocsLink | undefined;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-border-dashed px-6 py-10 text-center">
      <div className="text-[14px] font-semibold">{title}</div>
      {children && <p className="max-w-md text-[13px] text-fg-secondary">{children}</p>}
      {(action ?? docs) !== undefined && (
        <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
          {action}
          {docs && (
            <a
              href={docs.href}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[12.5px]"
            >
              {docs.label ?? "Read the guide"}
              <ExternalLink className="size-3.5" aria-hidden />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function ErrorState({
  title = "This didn't load",
  reason,
  requestId,
  onRetry,
}: {
  title?: ReactNode;
  reason: ReactNode;
  requestId?: string | undefined;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-card border border-danger/35 bg-danger/5 px-5 py-4"
    >
      <div className="text-[14px] font-semibold">{title}</div>
      <p className="text-[13px] text-fg-secondary">{reason}</p>
      {requestId && <p className="font-mono text-[11.5px] text-fg-muted">Request id {requestId}</p>}
      {onRetry && (
        <div className="pt-1">
          <Button size="30" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

/** Table-shaped skeleton: `rows` placeholder rows (default 8). */
export function LoadingRows({ rows = 8, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-[var(--row-h)] w-full" />
      ))}
    </div>
  );
}
