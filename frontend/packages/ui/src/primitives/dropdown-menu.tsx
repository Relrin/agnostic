import { DropdownMenu as MenuPrimitive } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "../lib/cn";

export const DropdownMenu = MenuPrimitive.Root;
export const DropdownMenuTrigger = MenuPrimitive.Trigger;
export const DropdownMenuGroup = MenuPrimitive.Group;

export function DropdownMenuContent({
  className,
  sideOffset = 4,
  ...props
}: ComponentProps<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-44 rounded-button border border-border bg-popover p-1 text-fg shadow-popover data-[state=open]:animate-in data-[state=open]:fade-in-0",
          className,
        )}
        {...props}
      />
    </MenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({
  className,
  destructive = false,
  ...props
}: ComponentProps<typeof MenuPrimitive.Item> & { destructive?: boolean }) {
  return (
    <MenuPrimitive.Item
      data-slot="dropdown-menu-item"
      className={cn(
        "flex h-8 cursor-pointer items-center gap-2 rounded-control px-2 text-[13px] outline-none select-none data-[disabled]:text-fg-disabled data-[highlighted]:bg-surface-hover [&_svg]:size-4 [&_svg]:text-fg-muted",
        destructive && "text-danger [&_svg]:text-danger",
        className,
      )}
      {...props}
    />
  );
}

export const DropdownMenuRadioGroup = MenuPrimitive.RadioGroup;

/** A choice in a `DropdownMenuRadioGroup`: a dot marks the selected one; children may span two lines. */
export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.RadioItem>) {
  return (
    <MenuPrimitive.RadioItem
      data-slot="dropdown-menu-radio-item"
      className={cn(
        "relative flex min-h-8 cursor-pointer items-start gap-2 rounded-control py-1.5 pr-2 pl-7 text-[13px] outline-none select-none data-[disabled]:text-fg-disabled data-[highlighted]:bg-surface-hover",
        className,
      )}
      {...props}
    >
      <span className="absolute top-[11px] left-2.5 flex size-2 items-center justify-center" aria-hidden>
        <MenuPrimitive.ItemIndicator>
          <span className="block size-2 rounded-full bg-fg" />
        </MenuPrimitive.ItemIndicator>
      </span>
      {children}
    </MenuPrimitive.RadioItem>
  );
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof MenuPrimitive.Label>) {
  return <MenuPrimitive.Label className={cn("eyebrow px-2 pt-2 pb-1", className)} {...props} />;
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn("my-1 h-px bg-border-subtle", className)} {...props} />;
}
