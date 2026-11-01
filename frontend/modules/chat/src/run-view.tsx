// One run in the conversation: header, live tool chips, member runs (teams), tasks, workflow step timeline, the
// response (markdown, citations), inline approvals or step HITL when paused, and the run toolbar.
import {
  attachRun,
  ensureRun,
  formatCount,
  formatDuration,
  runTokens,
  type RunState,
  type RunStream,
  type RunTarget,
  type StepNode,
  type StepRequirement,
  type ToolCall,
} from "@agnostic/core";
import {
  Button,
  Callout,
  MarkdownView,
  RunBlock,
  RunToolbar,
  StepHitlForm,
  StepTimeline,
  ToolCallChip,
  UserBubble,
  type HitlRequest,
  type HitlResolution,
  type StepView,
  type ToolChipStatus,
} from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import { Copy, GitFork, RotateCcw, ScanSearch } from "lucide-react";
import { useState } from "react";

import { RunApprovals } from "./approval";

const KIND = { agents: "agent", teams: "team", workflows: "workflow" } as const;

function chipStatus(tool: ToolCall): ToolChipStatus {
  if (tool.status === "paused") return tool.requiresConfirmation ? "awaiting" : "paused";
  return tool.status;
}

function chip(tool: ToolCall) {
  return (
    <ToolCallChip
      key={tool.id}
      name={tool.name}
      status={chipStatus(tool)}
      duration={tool.durationMs !== undefined ? `${(tool.durationMs / 1000).toFixed(1)}s` : undefined}
    />
  );
}

function toStepView(node: StepNode): StepView {
  const detail =
    node.kind === "loop" && node.iteration !== undefined
      ? `iteration ${String(node.iteration)}${node.maxIterations ? ` of ${String(node.maxIterations)}` : ""}`
      : node.kind === "router" && node.selected?.length
        ? `→ ${node.selected.join(", ")}`
        : node.error;
  return {
    id: node.id,
    name: node.name,
    kind: node.kind,
    status: node.status.toUpperCase(),
    detail,
    children: node.children.map(toStepView),
  };
}

export function toHitlRequest(requirement: StepRequirement): HitlRequest {
  const output = requirement.step_output;
  return {
    stepName: requirement.step_name ?? "step",
    confirmation: requirement.requires_confirmation
      ? (requirement.confirmation_message ?? "Confirm to continue the workflow.")
      : undefined,
    userInput: requirement.requires_user_input
      ? {
          message: requirement.user_input_message ?? undefined,
          fields: (requirement.user_input_schema ?? []).map((field) => ({
            name: field.name,
            type: field.field_type ?? "str",
            description: field.description ?? undefined,
            required: field.required ?? true,
            allowedValues: field.allowed_values?.map(String),
          })),
        }
      : undefined,
    routes: requirement.requires_route_selection
      ? {
          choices: requirement.available_choices ?? [],
          multiple: requirement.allow_multiple_selections ?? false,
        }
      : undefined,
    outputReview: requirement.requires_output_review
      ? typeof output === "string"
        ? output
        : JSON.stringify(output ?? {}, null, 2)
      : undefined,
  };
}

/** Apply a HITL answer to the requirement, as AgentOS expects it back in `step_requirements`. */
export function resolveRequirement(
  requirement: StepRequirement,
  resolution: HitlResolution,
): StepRequirement {
  return {
    ...requirement,
    confirmed: resolution.confirmed,
    ...(resolution.confirmed ? {} : { rejected: true }),
    ...(resolution.userInput ? { user_input: resolution.userInput } : {}),
    ...(resolution.selected ? { selected_choices: resolution.selected } : {}),
  };
}

function references(state: RunState): { key: string; label: string; href?: string | undefined }[] {
  const raw = state.citations;
  const urls =
    typeof raw === "object" && raw !== null && "urls" in raw && Array.isArray(raw.urls)
      ? (raw as { urls: { url?: string; title?: string }[] }).urls
      : [];
  return urls.flatMap((item, index) =>
    item.url ? [{ key: `${String(index)}-${item.url}`, label: item.title ?? item.url, href: item.url }] : [],
  );
}

export function RunView({
  state,
  stream,
  target,
  instanceName,
  componentName,
  versionLabel,
  onRetry,
  onFork,
}: {
  state: RunState;
  stream: RunStream | undefined;
  target: RunTarget;
  instanceName: string;
  componentName: string;
  versionLabel?: string | undefined;
  onRetry?: (() => void) | undefined;
  onFork?: (() => void) | undefined;
}) {
  const [copied, setCopied] = useState(false);
  const instance = target.instance;
  const family = target.family;
  // A paused run loaded from history gets a stream seeded with what is already known, so the transcript stays put.
  const live = (): RunStream => stream ?? ensureRun(target, state);
  const onContinued = () => {
    if (stream) void stream.resume({ fromStart: true });
    else
      attachRun(
        target,
        { runId: state.runId, sessionId: state.sessionId, input: state.input },
        { fromStart: true },
      );
  };
  const streaming = state.status === "running" || state.status === "pending";
  const worked =
    state.startedAt !== undefined && state.endedAt !== undefined
      ? `worked ${formatDuration(state.endedAt - state.startedAt)}`
      : streaming
        ? "working…"
        : undefined;
  const tokens = runTokens(state.metrics);
  const memberIds = state.memberOrder;
  const pausedTools = [
    ...state.tools.filter((tool) => tool.status === "paused"),
    ...memberIds.flatMap((id) => state.members[id]?.tools.filter((tool) => tool.status === "paused") ?? []),
  ];
  const sources = references(state);

  const confirmDirectly = (tool: ToolCall, confirmed: boolean, edited?: Record<string, unknown>) => {
    if (state.pause?.kind !== "tools") return;
    const tools = state.pause.tools.map((execution) =>
      (execution.tool_call_id ?? execution.tool_name) === tool.id
        ? { ...execution, confirmed, ...(edited ? { tool_args: edited } : {}) }
        : execution,
    );
    void live().continueRun({ tools: JSON.stringify(tools) });
  };

  const submitStep = (requirement: StepRequirement, resolution: HitlResolution) => {
    if (state.pause?.kind !== "steps") return;
    const all = state.pause.stepRequirements.map((item) =>
      item === requirement ? resolveRequirement(item, resolution) : item,
    );
    void live().continueRun({ step_requirements: JSON.stringify(all) });
  };

  return (
    <div className="flex flex-col gap-3">
      {state.input && <UserBubble>{state.input}</UserBubble>}
      <RunBlock
        label={`Run ${state.runId ?? "starting"}`}
        kind={KIND[family]}
        name={componentName}
        version={versionLabel}
        worked={worked}
        status={state.status}
        streaming={streaming}
        tools={
          state.tools.length > 0 || memberIds.length > 0 ? (
            <>
              {state.tools.map(chip)}
              {memberIds.flatMap((id) => state.members[id]?.tools.map(chip) ?? [])}
            </>
          ) : undefined
        }
        toolbar={
          state.status === "completed" || state.status === "error" || state.status === "cancelled" ? (
            <RunToolbar
              meta={`${state.runId ?? ""}${tokens !== undefined ? ` · ${formatCount(tokens)} tokens` : ""}`}
            >
              <Button
                variant="ghost"
                size="28"
                disabled={!state.content}
                onClick={() => {
                  void navigator.clipboard.writeText(state.content).then(() => {
                    setCopied(true);
                  });
                }}
              >
                <Copy aria-hidden />
                {copied ? "Copied" : "Copy response"}
              </Button>
              {onRetry && (
                <Button variant="ghost" size="28" onClick={onRetry}>
                  <RotateCcw aria-hidden />
                  Retry run
                </Button>
              )}
              {onFork && (
                <Button variant="ghost" size="28" onClick={onFork}>
                  <GitFork aria-hidden />
                  Fork session
                </Button>
              )}
              {state.runId && (
                <Button asChild variant="ghost" size="28">
                  <Link
                    to={`/i/${encodeURIComponent(instance)}/traces?run_id=${encodeURIComponent(state.runId)}`}
                  >
                    <ScanSearch aria-hidden />
                    View trace
                  </Link>
                </Button>
              )}
            </RunToolbar>
          ) : undefined
        }
      >
        {state.steps.length > 0 && <StepTimeline steps={state.steps.map(toStepView)} />}
        {state.tasks.length > 0 && (
          <ul
            aria-label="Team tasks"
            className="flex flex-col gap-1 rounded-tile border border-border bg-surface px-3 py-2 text-[12.5px]"
          >
            {state.tasks.map((task) => (
              <li key={task.id} className="flex items-center gap-2">
                <span className="font-mono text-fg-muted">{task.status}</span>
                <span>{task.title}</span>
                {task.assignee && <span className="ml-auto text-fg-muted">{task.assignee}</span>}
              </li>
            ))}
          </ul>
        )}
        {memberIds.length > 0 && (
          <details className="rounded-tile border border-border bg-surface px-3 py-2 text-[12.5px]">
            <summary className="cursor-pointer text-fg-secondary">
              {String(memberIds.length)} member {memberIds.length === 1 ? "run" : "runs"}
            </summary>
            <div className="flex flex-col gap-2 pt-2">
              {memberIds.map((id) => {
                const member = state.members[id];
                if (!member) return null;
                return (
                  <div
                    key={id}
                    className="flex flex-col gap-1"
                    style={{ paddingLeft: (member.depth - 1) * 12 }}
                  >
                    <span className="font-medium">{member.name}</span>
                    {member.content && <MarkdownView className="text-[13px]">{member.content}</MarkdownView>}
                  </div>
                );
              })}
            </div>
          </details>
        )}
        {state.reasoning && (
          <details className="text-[12.5px] text-fg-secondary">
            <summary className="cursor-pointer">Reasoning</summary>
            <p className="pt-1 whitespace-pre-wrap">{state.reasoning}</p>
          </details>
        )}
        {state.content && <MarkdownView>{state.content}</MarkdownView>}
        {sources.length > 0 && (
          <ol aria-label="Sources" className="flex flex-col gap-0.5 text-[12px] text-fg-muted">
            {sources.map((source, index) => (
              <li key={source.key}>
                [{index + 1}]{" "}
                <a
                  href={source.href}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-info hover:underline"
                >
                  {source.label}
                </a>
              </li>
            ))}
          </ol>
        )}
        {state.status === "paused" && state.pause?.kind !== "steps" && state.runId && (
          <RunApprovals
            instance={instance}
            instanceName={instanceName}
            onContinued={onContinued}
            runIds={[state.runId, ...memberIds]}
            pausedTools={pausedTools}
            onConfirmDirectly={confirmDirectly}
          />
        )}
        {state.status === "paused" &&
          state.pause?.kind === "steps" &&
          state.pause.stepRequirements.map((requirement, index) => (
            <StepHitlForm
              key={`${requirement.step_id ?? requirement.step_name ?? "step"}-${String(index)}`}
              request={toHitlRequest(requirement)}
              onSubmit={(resolution) => {
                submitStep(requirement, resolution);
              }}
            />
          ))}
        {state.status === "error" && (
          <Callout tone="danger" title={`Run failed${state.error?.type ? `: ${state.error.type}` : ""}`}>
            {state.error?.message}
          </Callout>
        )}
        {state.status === "cancelled" && (
          <Callout tone="info">Stopped{state.cancelReason ? `: ${state.cancelReason}` : "."}</Callout>
        )}
      </RunBlock>
    </div>
  );
}
