// The generated-code pane: Python projected from the draft (read-only), gutter marks against the base version,
// field↔line focus, approval notes, ruff status, and the raw config as `agent.json`.
import type { CodegenOut, SpanOut } from "@agnostic/api";
import { CodeView, CodeViewSkeleton, type ChangeMark, type CodeNote } from "@agnostic/editor";
import { Button, Tabs, TabsContent, TabsList, TabsTrigger, toast } from "@agnostic/ui";
import { Copy, Database } from "lucide-react";
import { useMemo, useState } from "react";

import type { Config } from "./config";

/** The field whose span holds `line`: the narrowest one (`instructions[2]` over `instructions`). */
export function pathAtLine(spans: Record<string, SpanOut>, line: number): string | undefined {
  let found: { path: string; size: number } | undefined;
  for (const [path, span] of Object.entries(spans)) {
    if (line < span.line || line > span.end_line) continue;
    const size = span.end_line - span.line;
    if (!found || size < found.size || (size === found.size && path.length > found.path.length)) {
      found = { path, size };
    }
  }
  return found?.path;
}

export function CodePane({
  code,
  config,
  kind,
  focusedPath,
  onFocusPath,
  registryHref,
  uncommitted,
  pending,
}: {
  code: CodegenOut | undefined;
  config: Config | undefined;
  kind: "agent" | "team";
  focusedPath: string | undefined;
  onFocusPath: (path: string | undefined) => void;
  /** Link for a note's "Open in Registry" action. */
  registryHref: (entry: string) => string;
  /** "↑ 1 unpublished · mode changed": what differs from the current version. */
  uncommitted: string | undefined;
  pending: boolean;
}) {
  const [cursor, setCursor] = useState<{ line: number; col: number } | undefined>(undefined);
  const marks = useMemo(() => {
    const out: Record<number, ChangeMark> = {};
    for (const [line, mark] of Object.entries(code?.marks ?? {})) out[Number(line)] = mark;
    return out;
  }, [code?.marks]);
  const notes = useMemo<CodeNote[]>(
    () =>
      (code?.notes ?? []).map((note) => ({
        line: note.line,
        from: note.col_start,
        to: note.col_end,
        text: note.message.replace(/`/g, ""),
        action: note.entry ? { label: "Open in Registry", href: registryHref(note.entry) } : undefined,
      })),
    [code?.notes, registryHref],
  );
  const focusLine = focusedPath ? code?.spans[focusedPath]?.line : undefined;
  const json = useMemo(() => JSON.stringify(config ?? {}, null, 2), [config]);
  const file = code?.filename ?? `${kind}s/${kind}.py`;
  const [folder, base] = file.includes("/")
    ? [file.slice(0, file.lastIndexOf("/") + 1), file.slice(file.lastIndexOf("/") + 1)]
    : ["", file];

  return (
    <section
      aria-label={kind === "team" ? "Team code" : "Agent code"}
      className="flex min-h-0 flex-col overflow-hidden rounded-card border border-border bg-inset"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle bg-canvas px-3 py-2 text-[12px]">
        <span className="inline-flex items-center gap-1.5 text-fg-secondary">
          <Database aria-hidden className="size-3.5" />
          Stored in Studio · registry refs only
        </span>
        <span className="flex-1" />
        {uncommitted && <span className="font-mono text-[11.5px] text-warning">{uncommitted}</span>}
      </div>
      <Tabs defaultValue="code" className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border-subtle px-3">
          <TabsList variant="underline" className="flex-1 border-0">
            <TabsTrigger value="code" className="font-mono text-[12px]">
              <span className="text-fg-muted">{folder}</span>
              {base}
            </TabsTrigger>
            <TabsTrigger value="json" className="font-mono text-[12px]">
              {kind}.json
            </TabsTrigger>
          </TabsList>
          <Button
            variant="icon"
            size="28"
            aria-label="Copy code"
            onClick={() => {
              void navigator.clipboard
                .writeText(code?.code ?? "")
                .then(() => toast.success("Copied the code."));
            }}
          >
            <Copy aria-hidden />
          </Button>
        </div>
        <TabsContent value="code" className="min-h-0 flex-1 overflow-auto">
          {code ? (
            <CodeView
              value={code.code}
              language="python"
              marks={marks}
              focusLine={focusLine}
              notes={notes}
              ariaLabel={`Generated ${file}`}
              onCursor={(line, col) => {
                setCursor({ line, col });
                const path = pathAtLine(code.spans, line);
                if (path && path !== focusedPath) onFocusPath(path);
              }}
            />
          ) : (
            <CodeViewSkeleton lines={14} />
          )}
        </TabsContent>
        <TabsContent value="json" className="min-h-0 flex-1 overflow-auto">
          <CodeView value={json} language="json" ariaLabel={`${kind}.json`} />
        </TabsContent>
      </Tabs>
      <div className="flex flex-wrap items-center gap-3 border-t border-border-subtle px-3 py-1.5 font-mono text-[11px] text-fg-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className={pending ? "size-1.5 rounded-full bg-warning" : "size-1.5 rounded-full bg-accent"}
          />
          {pending ? "Updating…" : "Synced with form"}
        </span>
        {cursor && <span>{`Ln ${String(cursor.line)}, Col ${String(cursor.col)}`}</span>}
        <span>{code?.ruff.status ?? "ruff"}</span>
        {notes.length > 0 && (
          <span className="text-warning">{`${String(notes.length)} note${notes.length === 1 ? "" : "s"}`}</span>
        )}
      </div>
    </section>
  );
}
