// The coding-agent badge: the harness's and the sandbox provider's logos, with the sandbox's image and limits in a
// tooltip.
import { BrandIcon, Tooltip, TooltipProvider, codingBrand, cn } from "@agnostic/ui";

import type { CodingSandbox } from "./api";

export const HARNESS_LABEL: Record<string, string> = { pi: "Pi", opencode: "OpenCode" };
export const SANDBOX_LABEL: Record<string, string> = { docker: "Docker", e2b: "E2B" };

function label(names: Record<string, string>, value: string): string {
  return names[value] ?? value;
}

function memory(megabytes: number): string {
  return megabytes >= 1024 && megabytes % 1024 === 0
    ? `${String(megabytes / 1024)} GB`
    : `${String(megabytes)} MB`;
}

/** "Docker sandbox · image agnostic-coding:0.1.0 · 2 CPUs · 2 GB · network isolated · 900 s per turn". */
export function sandboxSummary(sandbox: CodingSandbox | undefined): string[] {
  if (!sandbox) return [];
  const lines = [`${label(SANDBOX_LABEL, sandbox.provider)} sandbox`];
  if (sandbox.image) lines.push(`Image ${sandbox.image}`);
  const limits = [
    typeof sandbox.cpus === "number"
      ? `${String(sandbox.cpus)} ${sandbox.cpus === 1 ? "CPU" : "CPUs"}`
      : undefined,
    typeof sandbox.memory_mb === "number" ? memory(sandbox.memory_mb) : undefined,
  ].filter(Boolean);
  if (limits.length) lines.push(limits.join(" · "));
  if (sandbox.network) lines.push(`Network ${sandbox.network}`);
  if (typeof sandbox.turn_timeout_s === "number") lines.push(`${String(sandbox.turn_timeout_s)} s per turn`);
  return lines;
}

/** "Pi · Docker": a coding agent's harness and where it runs. */
export function CodingAgentBadge({
  harness,
  sandbox,
  className,
}: {
  harness: string;
  sandbox?: CodingSandbox | undefined;
  className?: string | undefined;
}) {
  const harnessBrand = codingBrand(harness);
  const sandboxBrand = sandbox ? codingBrand(sandbox.provider) : undefined;
  const name = label(HARNESS_LABEL, harness);
  const where = sandbox ? label(SANDBOX_LABEL, sandbox.provider) : undefined;
  const details = sandboxSummary(sandbox);
  const text = where ? `Coding agent: ${name} on ${where}` : `Coding agent: ${name}`;
  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip
        content={
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">{`Coding agent · ${name}`}</span>
            {details.length ? (
              details.map((line) => (
                <span key={line} className="font-mono text-[11.5px] text-fg-secondary">
                  {line}
                </span>
              ))
            ) : (
              <span className="text-fg-secondary">Runs each turn in its own sandbox.</span>
            )}
          </span>
        }
      >
        <button
          type="button"
          aria-label={text}
          data-coding-harness={harness}
          className={cn(
            "inline-flex h-6 shrink-0 cursor-default items-center gap-1.5 rounded-full border border-border-strong px-2 text-[11.5px] text-fg-secondary",
            className,
          )}
        >
          {harnessBrand && <BrandIcon brand={harnessBrand} className="size-3" />}
          <span>{name}</span>
          {where && (
            <>
              <span aria-hidden className="text-fg-faint">
                ·
              </span>
              {sandboxBrand && <BrandIcon brand={sandboxBrand} className="size-3" />}
              <span>{where}</span>
            </>
          )}
        </button>
      </Tooltip>
    </TooltipProvider>
  );
}
