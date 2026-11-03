// The code pane: the draft's Python, editable. Until someone edits it, it is generated from the form (gutter marks
// against the base version, approval notes); after that it is their code, read back into the form as they type, with
// diagnostics inline and the fields the form can't edit tinted as code-owned. Field↔line focus works both ways, and
// the raw config is the `agent.json` tab.
import type { CodegenOut, SpanOut } from "@agnostic/api";
import {
  CodeEditor,
  CodeView,
  CodeViewSkeleton,
  type ChangeMark,
  type CodeDiagnostic,
  type CodeNote,
  type LineRange,
} from "@agnostic/editor";
import { Button, Tabs, TabsContent, TabsList, TabsTrigger, toast } from "@agnostic/ui";
import { Code2, Copy, Database, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import type { Config, EditableKind } from "./config";
import type { SourceCode } from "./document";

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

/** The lines a field or step spans, for highlighting. */
export function spanLines(spans: Record<string, SpanOut>, path: string | undefined): LineRange | undefined {
  const span = path ? spans[path] : undefined;
  return span ? { from: span.line, to: span.end_line } : undefined;
}

const KIND_LABEL: Record<EditableKind, string> = { agent: "Agent", team: "Team", workflow: "Workflow" };

function status(source: SourceCode, pending: boolean): { text: string; tone: "ok" | "busy" | "problem" } {
  switch (source.state) {
    case "generated":
      return pending ? { text: "Updating…", tone: "busy" } : { text: "Synced with form", tone: "ok" };
    case "parsing":
      return { text: "Reading the code…", tone: "busy" };
    case "writing":
      return { text: "Writing the change into the code…", tone: "busy" };
    case "invalid":
      return { text: "Code doesn't parse · the form shows the last version that did", tone: "problem" };
    case "synced":
      return source.codeOwned.length > 0
        ? {
            text: `Synced with form · ${String(source.codeOwned.length)} code-owned`,
            tone: "ok",
          }
        : { text: "Synced with form", tone: "ok" };
  }
}

export function CodePane({
  code,
  source,
  onCode,
  onGenerate,
  config,
  kind,
  focusedPath,
  onFocusPath,
  registryHref,
  uncommitted,
  pending,
  readOnly = false,
}: {
  code: CodegenOut | undefined;
  source: SourceCode;
  /** A person edited the code (the draft becomes code-backed). */
  onCode: (code: string) => void;
  /** Go back to code generated from the form. */
  onGenerate: () => void;
  config: Config | undefined;
  kind: EditableKind;
  focusedPath: string | undefined;
  onFocusPath: (path: string | undefined) => void;
  /** Link for a note's "Open in Registry" action. */
  registryHref: (entry: string) => string;
  /** "↑ 1 unpublished · mode changed": what differs from the current version. */
  uncommitted: string | undefined;
  pending: boolean;
  readOnly?: boolean;
}) {
  const [cursor, setCursor] = useState<{ line: number; col: number } | undefined>(undefined);
  const backed = source.codeBacked;
  const value = backed ? source.code : code?.code;
  const spans = useMemo(
    () => (backed ? source.spans : (code?.spans ?? {})),
    [backed, source.spans, code?.spans],
  );
  const marks = useMemo(() => {
    const out: Record<number, ChangeMark> = {};
    if (backed) return out;
    for (const [line, mark] of Object.entries(code?.marks ?? {})) out[Number(line)] = mark;
    return out;
  }, [backed, code?.marks]);
  const notes = useMemo<CodeNote[]>(
    () =>
      backed
        ? []
        : (code?.notes ?? []).map((note) => ({
            line: note.line,
            from: note.col_start,
            to: note.col_end,
            text: note.message.replace(/`/g, ""),
            action: note.entry ? { label: "Open in Registry", href: registryHref(note.entry) } : undefined,
          })),
    [backed, code?.notes, registryHref],
  );
  const diagnostics = useMemo<CodeDiagnostic[]>(() => {
    const found: CodeDiagnostic[] = source.diagnostics.map((item) => ({
      line: item.line,
      column: item.column,
      endLine: item.end_line,
      endColumn: item.end_column,
      severity: item.severity,
      message: item.message,
    }));
    const ruff = backed ? source.ruff : code?.ruff;
    for (const message of ruff?.messages ?? []) {
      found.push({
        line: message.line,
        column: Math.max(message.column - 1, 0),
        endLine: message.line,
        endColumn: message.column,
        severity: "warning",
        message: `${message.code} ${message.message}`,
      });
    }
    return found;
  }, [backed, source.diagnostics, source.ruff, code?.ruff]);
  const owned = useMemo(
    () =>
      source.codeOwned.flatMap((path) => {
        const range = spanLines(spans, path);
        return range ? [range] : [];
      }),
    [source.codeOwned, spans],
  );
  const focus = spanLines(spans, focusedPath);
  const json = useMemo(() => JSON.stringify(config ?? {}, null, 2), [config]);
  const file = code?.filename ?? `${kind}s/${kind}.py`;
  const [folder, base] = file.includes("/")
    ? [file.slice(0, file.lastIndexOf("/") + 1), file.slice(file.lastIndexOf("/") + 1)]
    : ["", file];
  const shown = status(source, pending);

  return (
    <section
      aria-label={`${KIND_LABEL[kind]} code`}
      className="flex min-h-0 flex-col overflow-hidden rounded-card border border-border bg-inset"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle bg-canvas px-3 py-2 text-[12px]">
        {backed ? (
          <span className="inline-flex items-center gap-1.5 text-fg-secondary">
            <Code2 aria-hidden className="size-3.5" />
            Code-backed · your code is kept as written
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-fg-secondary">
            <Database aria-hidden className="size-3.5" />
            Stored in Studio · registry refs only
          </span>
        )}
        {backed && source.stale && (
          <span className="text-warning">The draft changed elsewhere since this code was saved.</span>
        )}
        <span className="flex-1" />
        {uncommitted && <span className="font-mono text-[11.5px] text-warning">{uncommitted}</span>}
        {backed && !readOnly && (
          <Button variant="ghost" size="28" onClick={onGenerate}>
            <RotateCcw aria-hidden />
            Use generated code
          </Button>
        )}
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
              void navigator.clipboard.writeText(value ?? "").then(() => toast.success("Copied the code."));
            }}
          >
            <Copy aria-hidden />
          </Button>
        </div>
        <TabsContent value="code" className="min-h-0 flex-1 overflow-auto">
          {value === undefined ? (
            <CodeViewSkeleton lines={14} />
          ) : (
            <CodeEditor
              value={value}
              onChange={onCode}
              language="python"
              marks={marks}
              focusRange={focus}
              notes={notes}
              diagnostics={diagnostics}
              ownedLines={owned}
              readOnly={readOnly}
              ariaLabel={backed ? file : `Generated ${file}`}
              onCursor={(line, col) => {
                setCursor({ line, col });
                const path = pathAtLine(spans, line);
                if (path && path !== focusedPath) onFocusPath(path);
              }}
            />
          )}
        </TabsContent>
        <TabsContent value="json" className="min-h-0 flex-1 overflow-auto">
          <CodeView value={json} language="json" ariaLabel={`${kind}.json`} />
        </TabsContent>
      </Tabs>
      <div className="flex flex-wrap items-center gap-3 border-t border-border-subtle px-3 py-1.5 font-mono text-[11px] text-fg-muted">
        <span className="inline-flex items-center gap-1.5" aria-live="polite">
          <span
            aria-hidden
            className={
              shown.tone === "ok"
                ? "size-1.5 rounded-full bg-accent"
                : shown.tone === "busy"
                  ? "size-1.5 rounded-full bg-warning"
                  : "size-1.5 rounded-full bg-danger"
            }
          />
          {shown.text}
        </span>
        {cursor && <span>{`Ln ${String(cursor.line)}, Col ${String(cursor.col)}`}</span>}
        <span>{(backed ? source.ruff : code?.ruff)?.status ?? "ruff"}</span>
        {diagnostics.length > 0 && (
          <span className="text-warning">{`${String(diagnostics.length)} problem${diagnostics.length === 1 ? "" : "s"}`}</span>
        )}
        {notes.length > 0 && (
          <span className="text-warning">{`${String(notes.length)} note${notes.length === 1 ? "" : "s"}`}</span>
        )}
      </div>
    </section>
  );
}
