import { ToggleGroup } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";

export type SegmentedOption<T extends string> = {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
};

export type SegmentedControlProps<T extends string> = {
  value: T;
  onValueChange: (value: T) => void;
  options: readonly SegmentedOption<T>[];
  /** Accessible name for the group, e.g. "Component type". */
  label: string;
  size?: "default" | "mini";
  className?: string;
};

/** Single-choice segmented control (container radius 9, 28px segments; 24px "mini"). */
export function SegmentedControl<T extends string>({
  value,
  onValueChange,
  options,
  label,
  size = "default",
  className,
}: SegmentedControlProps<T>) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label={label}
      value={value}
      onValueChange={(next) => {
        // Radix sends "" when the active segment is clicked again; a segmented control always keeps a value.
        if (next) onValueChange(next as T);
      }}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-segment border border-border bg-surface p-0.5",
        className,
      )}
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          disabled={option.disabled ?? false}
          className={cn(
            "inline-flex cursor-pointer items-center gap-1.5 rounded-control px-2.5 text-[12.5px] text-fg-secondary transition-colors hover:text-fg disabled:text-fg-disabled data-[state=on]:bg-segment-active data-[state=on]:text-fg-active",
            size === "mini" ? "h-6 px-2 text-[12px]" : "h-7",
          )}
        >
          {option.icon}
          {option.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
