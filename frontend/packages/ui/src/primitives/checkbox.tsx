// Checkbox (Radix), with an optional label and description beside it.
import { Check, Minus } from "lucide-react";
import { Checkbox as CheckboxPrimitive } from "radix-ui";
import { useId, type ComponentProps, type ReactNode } from "react";

import { cn } from "../lib/cn";

export type CheckboxProps = Omit<ComponentProps<typeof CheckboxPrimitive.Root>, "children"> & {
  label?: ReactNode;
  description?: ReactNode;
};

export function Checkbox({ className, label, description, id, ...props }: CheckboxProps) {
  const generated = useId();
  const boxId = id ?? generated;
  const box = (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      id={boxId}
      className={cn(
        "flex size-4 shrink-0 cursor-pointer items-center justify-center rounded-[4px] border border-border-strong bg-surface text-accent-fg transition-colors focus-visible:border-accent focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent",
        !label && className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center">
        {props.checked === "indeterminate" ? (
          <Minus className="size-3" strokeWidth={3} aria-hidden />
        ) : (
          <Check className="size-3" strokeWidth={3} aria-hidden />
        )}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
  if (!label) return box;
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <div className="flex h-5 items-center">{box}</div>
      <div className="flex flex-col gap-0.5">
        <label
          htmlFor={boxId}
          className={cn(
            "cursor-pointer text-[13px] text-fg",
            props.disabled && "cursor-not-allowed text-fg-disabled",
          )}
        >
          {label}
        </label>
        {description && <p className="text-[12.5px] text-fg-secondary">{description}</p>}
      </div>
    </div>
  );
}
