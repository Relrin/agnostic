import { X } from "lucide-react";
import { Dialog as SheetPrimitive } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "../lib/cn";
import { useReturnFocus } from "../lib/return-focus";

export const Sheet = SheetPrimitive.Root;
export const SheetTrigger = SheetPrimitive.Trigger;
export const SheetClose = SheetPrimitive.Close;
export const SheetTitle = SheetPrimitive.Title;
export const SheetDescription = SheetPrimitive.Description;

const SIDES = {
  right: "inset-y-0 right-0 h-full w-[min(440px,100%)] border-l data-[state=open]:slide-in-from-right",
  left: "inset-y-0 left-0 h-full w-[min(280px,100%)] border-r data-[state=open]:slide-in-from-left",
  bottom: "inset-x-0 bottom-0 max-h-[85vh] border-t data-[state=open]:slide-in-from-bottom",
} as const;

/** Side panel; inspector rails become a Sheet below 1024px. */
export function SheetContent({
  className,
  children,
  side = "right",
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: ComponentProps<typeof SheetPrimitive.Content> & { side?: keyof typeof SIDES }) {
  const returnFocus = useReturnFocus({ onOpenAutoFocus, onCloseAutoFocus });
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className="bg-black/50 fixed inset-0 z-50 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        className={cn(
          "fixed z-50 flex flex-col gap-4 border-border bg-rail p-5 text-fg shadow-popover duration-[var(--motion-panel)] data-[state=open]:animate-in",
          SIDES[side],
          className,
        )}
        {...props}
        {...returnFocus}
      >
        {children}
        <SheetPrimitive.Close
          aria-label="Close"
          className="absolute top-3 right-3 grid size-7 cursor-pointer place-items-center rounded-control text-fg-muted hover:bg-surface-hover hover:text-fg"
        >
          <X className="size-4" aria-hidden />
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  );
}
