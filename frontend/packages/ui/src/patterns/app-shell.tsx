import { Menu } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Sheet, SheetContent, SheetDescription, SheetTitle } from "../primitives/sheet";

/**
 * Page frame: sidebar column (248px) + main column whose regions scroll on their own.
 * Below 1024px the sidebar moves into a Sheet opened from a menu button.
 */
export function AppShell({ sidebar, children }: { sidebar: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex h-full min-h-screen bg-bg text-fg">
      <aside className="hidden w-[248px] shrink-0 border-r border-border-subtle lg:block">{sidebar}</aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="left"
          className="p-0"
          onClick={() => {
            setOpen(false);
          }}
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Pages of the control plane</SheetDescription>
          {sidebar}
        </SheetContent>
      </Sheet>
      <main className="flex min-w-0 flex-1 flex-col">
        <button
          type="button"
          aria-label="Open navigation"
          onClick={() => {
            setOpen(true);
          }}
          className="m-2 grid size-9 cursor-pointer place-items-center rounded-button border border-border bg-surface text-fg-secondary lg:hidden"
        >
          <Menu className="size-4" aria-hidden />
        </button>
        {children}
      </main>
    </div>
  );
}
