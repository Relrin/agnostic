// CodeView loads CodeMirror on first render (its own chunk), showing CodeViewSkeleton meanwhile.
import { Skeleton, cn } from "@agnostic/ui";
import { lazy, Suspense } from "react";

import type { CodeViewProps } from "./types";

const load = () => import("./code-view-impl");
const LazyCodeView = lazy(load);

/** Start fetching the editor chunk early (e.g. on hover of the "Code" layout toggle). */
export function preloadCodeView(): void {
  void load();
}

const WIDTHS = ["w-2/5", "w-3/5", "w-1/2", "w-4/5", "w-1/3", "w-2/3", "w-1/2", "w-3/4"];

/** Placeholder with the code view's gutter and line rhythm. */
export function CodeViewSkeleton({
  lines = 8,
  className,
}: {
  lines?: number;
  className?: string | undefined;
}) {
  return (
    <div
      data-slot="code-view-skeleton"
      role="status"
      aria-label="Loading code"
      className={cn("flex h-full min-h-0 flex-col gap-2 bg-inset py-3 pr-3 pl-4", className)}
    >
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className="flex items-center gap-4">
          <Skeleton className="h-3 w-5 shrink-0" />
          <Skeleton className={cn("h-3", WIDTHS[index % WIDTHS.length])} />
        </div>
      ))}
    </div>
  );
}

/** Read-only Python or JSON with change marks, a focused line and inline notes. */
export function CodeView(props: CodeViewProps) {
  return (
    <Suspense fallback={<CodeViewSkeleton className={props.className} />}>
      <LazyCodeView {...props} />
    </Suspense>
  );
}
