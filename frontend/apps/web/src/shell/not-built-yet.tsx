import { Callout, PageIntro } from "@agnostic/ui";

/** Placeholder for prototype pages whose module ships in a later phase. */
export function NotBuiltYet({ label, phase }: { label: string; phase: string }) {
  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title={label}>
        This page is part of the design and arrives with its module in {phase}.
      </PageIntro>
      <Callout tone="availability" title="Not built yet">
        The navigation already lists every page of the prototype so the shell matches the design. Modules
        replace these placeholders as they ship.
      </Callout>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Page not found">
        There's nothing at this address. Use the sidebar or ⌘K to find a page.
      </PageIntro>
    </div>
  );
}
