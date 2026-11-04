import { Callout, PageIntro } from "@agnostic/ui";

/** A navigation entry whose module isn't available here: disabled, or the instance lacks what it needs. */
export function Unavailable({ label }: { label: string }) {
  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title={label}>This page isn't available on this installation.</PageIntro>
      <Callout tone="availability" title="Not available">
        Its module is disabled, or the selected instance doesn't support it. An administrator can enable the
        module; the System page shows what each instance supports.
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
