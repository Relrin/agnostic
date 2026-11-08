// A coding agent's tool calls, drawn as what they did: a shell command with the tail of its output and its exit
// code, a file written (its path and first lines), an edit as a unified diff, and reads and searches as one line.
// Pi and OpenCode name their arguments differently (`path` / `filePath`, `oldText` / `oldString`); both are read.
// Any other tool (an MCP tool the agent was given) falls back to the plain tool chip.
import {
  Check,
  FilePen,
  FilePlus,
  FileText,
  FolderTree,
  LoaderCircle,
  Pause,
  Search,
  SquareTerminal,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { ToolCallChip, type ToolChipStatus } from "./run";

export const BASH_TAIL_LINES = 200;
export const WRITE_PREVIEW_LINES = 40;
const DIFF_MAX_LINES = 400;
/** Above this many line pairs the diff gives up on matching lines and shows old, then new. */
const DIFF_MAX_CELLS = 250_000;
const MCP_PREFIX = /^mcp__[^_]+(?:_[^_]+)*?__/;

export type CodingToolCallProps = {
  /** The normalised tool name: bash, read, write, edit, grep, find, ls, or anything else. */
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: ToolChipStatus;
  /** "0.4s". */
  duration?: string | undefined;
};

// ---------------------------------------------------------------- helpers

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function firstText(args: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = text(args[key]);
    if (value !== undefined) return value;
  }
  return undefined;
}

function resultText(result: unknown): string {
  if (result === undefined || result === null) return "";
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return "";
  }
}

function lines(value: string): string[] {
  if (value === "") return [];
  const split = value.replace(/\r\n/g, "\n").split("\n");
  if (split.at(-1) === "") split.pop();
  return split;
}

/** A bash result without its trailing `[exit code N]`, and that code (absent when the command succeeded). */
export function splitExitCode(output: string): { output: string; exitCode: number | undefined } {
  const match = /\n?\[exit code (-?\d+)\]\s*$/.exec(output);
  if (!match) return { output, exitCode: undefined };
  return { output: output.slice(0, match.index), exitCode: Number(match[1]) };
}

/** The last `count` lines, and how many came before them. */
export function tail(value: string, count: number): { lines: string[]; hidden: number } {
  const all = lines(value);
  return all.length <= count
    ? { lines: all, hidden: 0 }
    : { lines: all.slice(-count), hidden: all.length - count };
}

export type CodeDiffLine = { kind: "context" | "add" | "remove"; text: string };

/** A line diff of two texts (longest common subsequence), unchanged lines included. */
export function lineDiff(before: string, after: string): CodeDiffLine[] {
  const a = lines(before);
  const b = lines(after);
  if (a.length * b.length > DIFF_MAX_CELLS) {
    return [
      ...a.map((line) => ({ kind: "remove" as const, text: line })),
      ...b.map((line) => ({ kind: "add" as const, text: line })),
    ];
  }
  // lengths[i][j]: the LCS length of a[i:] and b[j:].
  const width = b.length + 1;
  const lengths = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lengths[i * width + j] =
        a[i] === b[j]
          ? (lengths[(i + 1) * width + j + 1] ?? 0) + 1
          : Math.max(lengths[(i + 1) * width + j] ?? 0, lengths[i * width + j + 1] ?? 0);
    }
  }
  const diff: CodeDiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      diff.push({ kind: "context", text: a[i] ?? "" });
      i++;
      j++;
    } else if ((lengths[(i + 1) * width + j] ?? 0) >= (lengths[i * width + j + 1] ?? 0)) {
      diff.push({ kind: "remove", text: a[i] ?? "" });
      i++;
    } else {
      diff.push({ kind: "add", text: b[j] ?? "" });
      j++;
    }
  }
  for (; i < a.length; i++) diff.push({ kind: "remove", text: a[i] ?? "" });
  for (; j < b.length; j++) diff.push({ kind: "add", text: b[j] ?? "" });
  return diff;
}

/** The replacements an edit call made: Pi's `oldText`/`newText` or `edits[]`, OpenCode's `oldString`/`newString`. */
export function editPairs(args: Record<string, unknown>): { before: string; after: string }[] {
  const single = (item: Record<string, unknown>) => {
    const before = firstText(item, "oldText", "oldString", "old_string", "old_text");
    const after = firstText(item, "newText", "newString", "new_string", "new_text");
    return before !== undefined || after !== undefined
      ? { before: before ?? "", after: after ?? "" }
      : undefined;
  };
  if (Array.isArray(args.edits)) {
    return args.edits.flatMap((item: unknown) => {
      const pair =
        typeof item === "object" && item !== null ? single(item as Record<string, unknown>) : undefined;
      return pair ? [pair] : [];
    });
  }
  const pair = single(args);
  return pair ? [pair] : [];
}

function pathOf(args: Record<string, unknown>): string | undefined {
  return firstText(args, "path", "filePath", "file_path", "filename");
}

// ---------------------------------------------------------------- pieces

function StatusIcon({ status }: { status: ToolChipStatus }) {
  if (status === "running") return <LoaderCircle className="size-3 animate-spin text-fg-muted" aria-hidden />;
  if (status === "done") return <Check className="size-3 text-accent" aria-hidden />;
  if (status === "error") return <X className="size-3 text-danger" aria-hidden />;
  return <Pause className="size-3 text-warning" aria-hidden />;
}

const STATUS_TEXT: Record<ToolChipStatus, string> = {
  running: "running",
  done: "done",
  error: "failed",
  paused: "paused",
  awaiting: "awaiting approval",
};

function Card({
  label,
  icon: Icon,
  tool,
  title,
  status,
  duration,
  extra,
  children,
}: {
  label: string;
  icon: LucideIcon;
  tool: string;
  title?: string | undefined;
  status: ToolChipStatus;
  duration?: string | undefined;
  extra?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      data-coding-tool={tool}
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-tile border bg-surface text-[12.5px]",
        status === "error" ? "border-danger/40" : "border-border",
      )}
    >
      <div className="flex min-w-0 items-center gap-2 px-2.5 py-1.5">
        <Icon className="size-3.5 shrink-0 text-fg-muted" aria-hidden />
        <span className="shrink-0 font-mono text-[11.5px] text-fg-muted">{tool}</span>
        {title && <span className="min-w-0 truncate font-mono text-[12px] text-fg">{title}</span>}
        <span className="flex-1" />
        {extra}
        {duration && status !== "running" && (
          <span className="shrink-0 font-mono text-[11px] text-fg-muted">{duration}</span>
        )}
        <span className="inline-flex shrink-0 items-center" title={STATUS_TEXT[status]}>
          <StatusIcon status={status} />
          <span className="sr-only">{STATUS_TEXT[status]}</span>
        </span>
      </div>
      {children}
    </div>
  );
}

function Pre({ children, className, label }: { children: ReactNode; className?: string; label: string }) {
  return (
    <pre
      aria-label={label}
      className={cn(
        "max-h-80 overflow-auto border-t border-border-subtle bg-inset px-2.5 py-2 font-mono text-[11.5px] leading-[1.55] whitespace-pre text-fg-secondary",
        className,
      )}
    >
      {children}
    </pre>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <span className="block text-fg-faint italic">{children}</span>;
}

function plural(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`;
}

// ---------------------------------------------------------------- per tool

function BashCall({ args, result, status, duration }: CodingToolCallProps) {
  const command = firstText(args, "command", "cmd") ?? "";
  const { output, exitCode } = splitExitCode(resultText(result));
  const shown = tail(output, BASH_TAIL_LINES);
  const failed = exitCode !== undefined && exitCode !== 0;
  const pill =
    status === "running" ? undefined : (
      <span
        className={cn(
          "shrink-0 rounded-full px-1.5 font-mono text-[10.5px] leading-[18px]",
          failed || status === "error" ? "bg-danger/12 text-danger" : "bg-accent/12 text-accent",
        )}
      >
        {`exit ${String(exitCode ?? (status === "error" ? 1 : 0))}`}
      </span>
    );
  return (
    <Card
      label={`bash: ${command}`}
      icon={SquareTerminal}
      tool="bash"
      status={status}
      duration={duration}
      extra={pill}
    >
      <Pre label="Command" className="max-h-40 text-fg">
        <span className="text-fg-muted select-none">$ </span>
        {command}
      </Pre>
      {shown.lines.length > 0 && (
        <Pre label="Output">
          {shown.hidden > 0 && <Note>{`… ${plural(shown.hidden, "earlier line")}`}</Note>}
          {shown.lines.join("\n")}
        </Pre>
      )}
    </Card>
  );
}

function WriteCall({ args, status, duration }: CodingToolCallProps) {
  const path = pathOf(args) ?? "";
  const content = firstText(args, "content", "text") ?? "";
  const all = lines(content);
  const preview = all.slice(0, WRITE_PREVIEW_LINES);
  return (
    <Card
      label={`write: ${path}`}
      icon={FilePlus}
      tool="write"
      title={path}
      status={status}
      duration={duration}
      extra={
        <span className="shrink-0 font-mono text-[11px] text-fg-muted">{plural(all.length, "line")}</span>
      }
    >
      {preview.length > 0 && (
        <Pre label={`Contents of ${path}`}>
          {preview.join("\n")}
          {all.length > preview.length && (
            <Note>{`… ${plural(all.length - preview.length, "more line")}`}</Note>
          )}
        </Pre>
      )}
    </Card>
  );
}

const DIFF_STYLE: Record<CodeDiffLine["kind"], { sign: string; className: string }> = {
  add: { sign: "+", className: "bg-accent/10 text-accent" },
  remove: { sign: "-", className: "bg-danger/10 text-danger" },
  context: { sign: " ", className: "text-fg-muted" },
};

function EditCall({ args, status, duration }: CodingToolCallProps) {
  const path = pathOf(args) ?? "";
  const pairs = editPairs(args);
  const diff = pairs.flatMap((pair, index) => {
    const hunk = lineDiff(pair.before, pair.after);
    return index > 0 ? [{ kind: "context" as const, text: "…" }, ...hunk] : hunk;
  });
  const added = diff.filter((line) => line.kind === "add").length;
  const removed = diff.filter((line) => line.kind === "remove").length;
  const shown = diff.slice(0, DIFF_MAX_LINES);
  return (
    <Card
      label={`edit: ${path}`}
      icon={FilePen}
      tool="edit"
      title={path}
      status={status}
      duration={duration}
      extra={
        <span className="shrink-0 font-mono text-[11px]">
          <span className="text-accent">{`+${String(added)}`}</span>{" "}
          <span className="text-danger">{`−${String(removed)}`}</span>
        </span>
      }
    >
      {shown.length > 0 && (
        <pre
          aria-label={`Diff of ${path}`}
          className="max-h-80 overflow-auto border-t border-border-subtle bg-inset py-1 font-mono text-[11.5px] leading-[1.55]"
        >
          {shown.map((line, index) => (
            <span
              // Lines repeat, and the diff never reorders: the index is the identity.
              key={index}
              data-diff={line.kind}
              className={cn("block px-2.5 whitespace-pre", DIFF_STYLE[line.kind].className)}
            >
              <span aria-hidden className="inline-block w-3 select-none">
                {DIFF_STYLE[line.kind].sign}
              </span>
              {line.text}
            </span>
          ))}
          {diff.length > shown.length && (
            <span className="block px-2.5 text-fg-faint italic">
              {`… ${plural(diff.length - shown.length, "more line")}`}
            </span>
          )}
        </pre>
      )}
    </Card>
  );
}

const COMPACT: Record<
  string,
  { icon: LucideIcon; target: (args: Record<string, unknown>) => string | undefined }
> = {
  read: { icon: FileText, target: pathOf },
  ls: { icon: FolderTree, target: (args) => pathOf(args) ?? "." },
  grep: {
    icon: Search,
    target: (args) => {
      const pattern = firstText(args, "pattern", "query", "regex");
      const where = pathOf(args) ?? firstText(args, "include", "glob");
      return [pattern, where && `in ${where}`].filter(Boolean).join(" ") || undefined;
    },
  },
  find: {
    icon: Search,
    target: (args) => {
      const pattern = firstText(args, "pattern", "glob", "name");
      const where = pathOf(args);
      return [pattern, where && `in ${where}`].filter(Boolean).join(" ") || undefined;
    },
  },
};

function CompactCall({ name, args, result, status, duration }: CodingToolCallProps) {
  const spec = COMPACT[name];
  if (!spec) return null;
  const target = spec.target(args);
  const count = lines(resultText(result)).length;
  return (
    <Card
      label={`${name}: ${target ?? ""}`}
      icon={spec.icon}
      tool={name}
      title={target}
      status={status}
      duration={duration}
      extra={
        status === "done" && count > 0 ? (
          <span className="shrink-0 font-mono text-[11px] text-fg-muted">{plural(count, "line")}</span>
        ) : undefined
      }
    />
  );
}

/** One tool call of a coding agent. */
export function CodingToolCall(props: CodingToolCallProps) {
  switch (props.name) {
    case "bash":
      return <BashCall {...props} />;
    case "write":
      return <WriteCall {...props} />;
    case "edit":
      return <EditCall {...props} />;
    case "read":
    case "grep":
    case "find":
    case "ls":
      return <CompactCall {...props} />;
    default:
      return (
        <span className="self-start">
          <ToolCallChip
            name={props.name.replace(MCP_PREFIX, "")}
            status={props.status}
            duration={props.duration}
          />
        </span>
      );
  }
}
