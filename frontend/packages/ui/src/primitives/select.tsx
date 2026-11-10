import { Check, ChevronDown } from "lucide-react";
import { Select as SelectPrimitive } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "../lib/cn";

export const Select = SelectPrimitive.Root;
export const SelectGroup = SelectPrimitive.Group;

/** The selected option's text in the trigger. Radix ignores `className` here, so the trigger styles it by slot. */
export function SelectValue(props: ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />;
}

export function SelectTrigger({
  className,
  children,
  ...props
}: ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(
        "flex h-[var(--control-h-34)] w-full min-w-0 cursor-pointer items-center justify-between gap-2 rounded-button border border-border-input bg-surface px-2.5 text-left text-[13px] text-fg focus-visible:border-accent focus-visible:outline-none disabled:text-fg-disabled data-[placeholder]:text-fg-muted",
        // A long value is cut with an ellipsis instead of running over the border and the chevron.
        "*:data-[slot=select-value]:min-w-0 *:data-[slot=select-value]:truncate",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="size-4 shrink-0 text-fg-muted" aria-hidden />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  position = "popper",
  ...props
}: ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        position={position}
        sideOffset={4}
        className={cn(
          "z-50 max-h-[var(--radix-select-content-available-height)] max-w-[min(var(--radix-select-content-available-width),28rem)] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-button border border-border bg-popover p-1 text-fg shadow-popover data-[state=open]:animate-in data-[state=open]:fade-in-0",
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

/** An option. A label too long for the list is cut with an ellipsis; `title` (the label, when it is text) has it whole. */
export function SelectItem({
  className,
  children,
  title,
  ...props
}: ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      title={title ?? (typeof children === "string" ? children : undefined)}
      className={cn(
        "relative flex h-8 min-w-0 cursor-pointer items-center rounded-control pr-8 pl-2 text-[13px] outline-none select-none data-[disabled]:text-fg-disabled data-[highlighted]:bg-surface-hover",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText className="min-w-0 truncate">{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="absolute right-2">
        <Check className="size-4 text-accent" aria-hidden />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}
