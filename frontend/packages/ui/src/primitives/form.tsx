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
  hideLabel = false,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  /** Only screen readers get the label (a switch in a table row: "Enable daily-brief"). */
  hideLabel?: boolean;
}) {
  const id = useId();
  return (
    <div className={cn("items-start", hideLabel ? "inline-flex" : "flex justify-between gap-4")}>
      <div className={cn("flex flex-col gap-0.5", hideLabel && "sr-only")}>
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
            "absolute top-0.5 left-0 size-3.5 rounded-full transition-transform",
            checked ? "translate-x-[18px] bg-accent-fg" : "translate-x-0.5 bg-fg-secondary",
          )}
        />
      </button>
    </div>
  );
}

export type RadioCardOption<T extends string> = { value: T; label: ReactNode; description?: ReactNode };

/** A radio group drawn as cards (selected: lime border and tint), e.g. the eval type of a new evaluation. */
export function RadioCards<T extends string>({
  legend,
  value,
  onValueChange,
  options,
  className,
}: {
  legend: ReactNode;
  value: T;
  onValueChange: (value: T) => void;
  options: readonly RadioCardOption<T>[];
  className?: string;
}) {
  const name = useId();
  return (
    <fieldset className={cn("flex flex-col gap-2", className)}>
      <legend className="mb-1.5 text-[13px] font-medium text-fg-secondary">{legend}</legend>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2">
        {options.map((option) => {
          const checked = option.value === value;
          return (
            <label
              key={option.value}
              className={cn(
                "flex cursor-pointer flex-col gap-0.5 rounded-radio border px-3 py-2.5 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                checked ? "border-accent bg-accent/6" : "border-border hover:bg-surface-hover",
              )}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={checked}
                onChange={() => {
                  onValueChange(option.value);
                }}
                className="sr-only"
              />
              <span className="text-[13px] font-medium">{option.label}</span>
              {option.description && <span className="text-[12px] text-fg-muted">{option.description}</span>}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
