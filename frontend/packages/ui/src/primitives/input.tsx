import type { ComponentProps } from "react";

import { cn } from "../lib/cn";

export type InputProps = ComponentProps<"input"> & {
  /** Monospace text, for ids, scopes and keys. */
  mono?: boolean;
};

export function Input({ className, mono = false, type = "text", ...props }: InputProps) {
  return (
    <input
      data-slot="input"
      type={type}
      className={cn(
        "h-[34px] w-full min-w-0 rounded-control border border-border-input bg-inset px-2.5 text-[13px] text-fg transition-colors placeholder:text-fg-muted focus-visible:border-accent focus-visible:shadow-selection focus-visible:outline-none disabled:text-fg-disabled aria-invalid:border-danger",
        mono && "font-mono text-[12.5px]",
        className,
      )}
      {...props}
    />
  );
}
