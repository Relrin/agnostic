// One answer: tool chips as it looks things up, the text, the pages it used (in-app links), and a label that says
// a model wrote it. Reuses the run widgets so answers look like the runs they talk about.
import { formatDuration } from "@agnostic/core";
import {
  Button,
  Callout,
  MarkdownView,
  Provenance,
  RunBlock,
  RunToolbar,
  ToolCallChip,
  type ToolChipStatus,
} from "@agnostic/ui";
import { useNavigate } from "@tanstack/react-router";
import { Copy, RefreshCw, Square } from "lucide-react";

import { settled, type AnswerSource, type AnswerState, type AnswerTool } from "./answer";

const CHIP: Record<AnswerTool["status"], ToolChipStatus> = {
  running: "running",
  done: "done",
  denied: "error",
  not_found: "error",
  error: "error",
};

const STATUS: Record<AnswerState["status"], string> = {
  idle: "queued",
  queued: "queued",
  streaming: "running",
  completed: "completed",
  failed: "error",
  cancelled: "cancelled",
};

export const GROUNDING = "answers use your traces, sessions and audit log";

export function SourceList({ sources }: { sources: readonly AnswerSource[] }) {
  const navigate = useNavigate();
  if (sources.length === 0) return null;
  return (
    <ol aria-label="Sources" className="flex flex-col gap-0.5 text-[12px] text-fg-muted">
      {sources.map((source, index) => (
        <li key={source.path}>
          [{index + 1}]{" "}
          <a
            href={source.path}
            className="text-info hover:underline"
            onClick={(event) => {
              event.preventDefault();
              void navigate({ href: source.path });
            }}
          >
            {source.label}
          </a>
        </li>
      ))}
    </ol>
  );
}

export function ToolChips({ tools }: { tools: readonly AnswerTool[] }) {
  return tools.map((tool) => (
    <span key={tool.id} title={tool.detail ?? undefined}>
      <ToolCallChip
        name={tool.name}
        status={CHIP[tool.status]}
        duration={tool.durationMs ? formatDuration(tool.durationMs) : undefined}
      />
    </span>
  ));
}

export function AnswerView({
  state,
  onStop,
  onRegenerate,
}: {
  state: AnswerState;
  onStop?: (() => void) | undefined;
  onRegenerate?: (() => void) | undefined;
}) {
  const writing = !settled(state);
  return (
    <RunBlock
      label="Answer from Ask your OS"
      kind="agent"
      name="Ask your OS"
      status={STATUS[state.status]}
      streaming={state.status === "streaming"}
      tools={state.tools.length > 0 ? <ToolChips tools={state.tools} /> : undefined}
      toolbar={
        <RunToolbar
          meta={
            state.status === "completed" ? (
              <Provenance>
                Generated{state.model ? ` by ${state.model}` : ""} · {GROUNDING}
              </Provenance>
            ) : undefined
          }
        >
          {writing && onStop && (
            <Button variant="ghost" size="28" onClick={onStop}>
              <Square aria-hidden /> Stop
            </Button>
          )}
          {!writing && state.content && (
            <Button
              variant="ghost"
              size="28"
              onClick={() => {
                void navigator.clipboard.writeText(state.content);
              }}
            >
              <Copy aria-hidden /> Copy
            </Button>
          )}
          {!writing && onRegenerate && (
            <Button variant="ghost" size="28" onClick={onRegenerate}>
              <RefreshCw aria-hidden /> Ask again
            </Button>
          )}
        </RunToolbar>
      }
    >
      {state.status === "queued" || (state.status === "idle" && !state.content) ? (
        <p className="text-[13px] text-fg-muted">Looking into it…</p>
      ) : null}
      {state.content && <MarkdownView streaming={writing}>{state.content}</MarkdownView>}
      {state.status === "failed" && <Callout tone="danger">{state.error}</Callout>}
      {state.status === "cancelled" && <p className="text-[12px] text-fg-muted">Stopped.</p>}
      <SourceList sources={state.sources} />
    </RunBlock>
  );
}
