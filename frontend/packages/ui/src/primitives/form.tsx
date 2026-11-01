// Form building blocks: a labelled field with hint and error, textarea, switch.
import { useId, type ComponentProps, type ReactNode } from "react";

import { cn } from "../lib/cn";

/** Label + control + hint/error. The render prop receives the ids to wire `aria-describedby`. */
export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  className?: string;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy =
    [hint ? hintId : undefined, error ? errorId : undefined].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[13px] font-medium text-fg-secondary">
        {label}
      </label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {hint && !error && (
        <p id={hintId} className="text-[12px] text-fg-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-[12.5px] text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-24 w-full rounded-button border border-border-input bg-surface px-2.5 py-2 font-mono text-[12.5px] text-fg placeholder:text-fg-muted focus-visible:border-accent focus-visible:outline-none aria-invalid:border-danger",
        className,
      )}
      {...props}
    />
  );
}

/** An on/off switch (a checkbox with role="switch"). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex flex-col gap-0.5">
        <label htmlFor={id} className="text-[13.5px] font-medium">
          {label}
        </label>
        {description && <p className="text-[12.5px] text-fg-secondary">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => {
          onCheckedChange(!checked);
        }}
        className={cn(
          "relative h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          checked ? "border-accent bg-accent" : "border-border-strong bg-surface-hover",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "absolute top-0.5 size-3.5 rounded-full transition-transform",
            checked ? "translate-x-[18px] bg-accent-fg" : "translate-x-0.5 bg-fg-secondary",
          )}
        />
      </button>
    </div>
  );
}
