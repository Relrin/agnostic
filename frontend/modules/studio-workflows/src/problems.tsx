// What the server's workflow validation found, by node: the problems panel, and the counts the canvas badges show.
import type { DiagnosticOut, WorkflowValidationOut } from "@agnostic/api";
import { cn } from "@agnostic/ui";
import { CircleAlert, Info, TriangleAlert } from "lucide-react";

import { useBuilderContext } from "./context";
import { nodeAt, nodeName, parsePath } from "./tree";

/** The node a diagnostic is about: its path up to the last `[n]` (`steps[1].selector` → `steps[1]`). */
export function nodePathOf(path: string): string | undefined {
  const match = /^(.*\])/.exec(path);
  return match?.[1] && parsePath(match[1]).length ? match[1] : undefined;
}

export function diagnosticsOf(validation: WorkflowValidationOut | undefined): DiagnosticOut[] {
  return (validation?.validation.layers ?? []).flatMap((layer) => layer.diagnostics);
}

/** Errors and warnings per node path (infos aren't counted on the canvas). */
export function problemCounts(validation: WorkflowValidationOut | undefined): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of diagnosticsOf(validation)) {
    if (item.severity === "info") continue;
    const path = nodePathOf(item.path);
    if (path) counts.set(path, (counts.get(path) ?? 0) + 1);
  }
  return counts;
}

const ICONS = {
  error: <CircleAlert aria-hidden className="size-3.5 shrink-0 text-danger" />,
  warning: <TriangleAlert aria-hidden className="size-3.5 shrink-0 text-warning" />,
  info: <Info aria-hidden className="size-3.5 shrink-0 text-info" />,
};

export function ProblemsPanel({ validation }: { validation: WorkflowValidationOut | undefined }) {
  const { store, doc } = useBuilderContext();
  const items = diagnosticsOf(validation);
  if (items.length === 0) return null;
  return (
    <section
      aria-label="Problems"
      className="max-h-44 shrink-0 overflow-y-auto border-t border-border bg-surface px-3 py-2"
    >
      <h2 className="mb-1 text-[12px] font-medium text-fg-secondary">{`Problems · ${String(items.length)}`}</h2>
      <ul className="flex flex-col">
        {items.map((item, index) => {
          const path = nodePathOf(item.path);
          const name = path ? nodeName(nodeAt(doc.config, path)) : "";
          return (
            <li key={`${item.path}-${item.code}-${String(index)}`}>
              <button
                type="button"
                disabled={!path}
                className={cn(
                  "flex w-full items-start gap-2 rounded-control px-2 py-1 text-left text-[12.5px]",
                  path && "hover:bg-surface-hover",
                )}
                onClick={() => {
                  if (path) store.getState().select(path);
                }}
              >
                {ICONS[item.severity]}
                <span className="flex-1">{item.message}</span>
                <span className="font-mono text-[11px] text-fg-muted">{name || item.path || "workflow"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
