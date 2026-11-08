// The Sessions detail aside: actions with API/scope hints, and the Chat, Runs, Summary, State and
// Metrics tabs.
import { describeError } from "@agnostic/api";
import {
  PermissionGate,
  SessionArtifacts,
  formatCount,
  formatDuration,
  formatWhen,
  fromStoredRun,
  runTokens,
  useCan,
  useSession,
  useSessionActions,
  useSessionRuns,
  type RunState,
  type SessionDetail,
} from "@agnostic/core";
import {
  ApiHint,
  Button,
  Callout,
  EmptyState,
  ErrorState,
  JsonEditor,
  JsonView,
  LoadingRows,
  MarkdownView,
  Provenance,
  RunCard,
  RunTimelineSeparator,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  ToolCallChip,
  UserBubble,
} from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useState } from "react";

export type Tab = "chat" | "runs" | "files" | "summary" | "state" | "metrics";
export const TABS: readonly { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "runs", label: "Runs" },
  { id: "files", label: "Files" },
  { id: "summary", label: "Summary" },
  { id: "state", label: "State" },
  { id: "metrics", label: "Metrics" },
];

type Owner = { family: "agents" | "teams" | "workflows"; id: string };

export function ownerOf(session: {
  agent_id?: string | null;
  team_id?: string | null;
  workflow_id?: string | null;
}): Owner | undefined {
  if (session.workflow_id) return { family: "workflows", id: session.workflow_id };
  if (session.team_id) return { family: "teams", id: session.team_id };
  if (session.agent_id) return { family: "agents", id: session.agent_id };
  return undefined;
}

/** A sentence about what happened in a run (Runs tab). */
export function runNote(run: RunState): string {
  const paused = run.tools.find((tool) => tool.status === "paused");
  switch (run.status) {
    case "paused":
      return paused
        ? `Paused on ${paused.name} for approval. Continues when someone resolves it.`
        : "Paused, waiting for input on a workflow step.";
    case "error":
      return `Failed${run.error?.type ? ` with ${run.error.type}` : ""}: ${run.error?.message ?? "no details."}`;
    case "cancelled":
      return "Stopped before it finished.";
    case "running":
    case "pending":
      return "Still running.";
    default: {
      const tools = run.tools.length;
      return tools
        ? `Completed after ${String(tools)} tool ${tools === 1 ? "call" : "calls"}.`
        : "Completed without tool calls.";
    }
  }
}

function duration(run: RunState): number | undefined {
  const value = run.metrics?.duration;
  if (typeof value === "number") return value * 1000;
  return run.startedAt !== undefined && run.endedAt !== undefined ? run.endedAt - run.startedAt : undefined;
}

function ChatTab({ instance, runs }: { instance: string; runs: readonly RunState[] }) {
  if (runs.length === 0) return <EmptyState title="No runs in this session yet" />;
  return (
    <div className="flex flex-col gap-4">
      {runs.map((run, index) => {
        const paused = run.tools.filter((tool) => tool.status === "paused");
        return (
          <div key={run.runId ?? index} className="flex flex-col gap-2.5">
            <RunTimelineSeparator>
              Run {index + 1} · {formatWhen(run.startedAt)} · {run.status}
            </RunTimelineSeparator>
            {run.input && <UserBubble>{run.input}</UserBubble>}
            {run.tools.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {run.tools.map((tool) => (
                  <ToolCallChip
                    key={tool.id}
                    name={tool.name}
                    status={tool.status === "paused" ? "awaiting" : tool.status}
                    duration={
                      tool.durationMs !== undefined ? `${(tool.durationMs / 1000).toFixed(1)}s` : undefined
                    }
                  />
                ))}
              </div>
            )}
            {run.content && <MarkdownView>{run.content}</MarkdownView>}
            {run.status === "error" && (
              <Callout tone="danger" title={`Run failed${run.error?.type ? `: ${run.error.type}` : ""}`}>
                {run.error?.message}
              </Callout>
            )}
            {paused.map((tool) => (
              <Callout
                key={tool.id}
                tone="warning"
                action={
                  <Button asChild size="28" variant="outline">
                    <Link
                      to={`/i/${encodeURIComponent(instance)}/approvals?tool=${encodeURIComponent(tool.name)}`}
                    >
                      Open in Approvals
                    </Link>
                  </Button>
                }
              >
                <code className="font-mono">
                  {tool.name}(
                  {Object.entries(tool.args)
                    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
                    .join(", ")}
                  )
                </code>{" "}
                is waiting on approval.
              </Callout>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function RunsTab({ instance, runs }: { instance: string; runs: readonly RunState[] }) {
  if (runs.length === 0) return <EmptyState title="No runs in this session yet" />;
  return (
    <div className="flex flex-col gap-2">
      {[...runs].reverse().map((run) => {
        const tokens = runTokens(run.metrics);
        const took = duration(run);
        return (
          <RunCard
            key={run.runId}
            status={run.status}
            title={run.input ?? run.runId}
            meta={[
              run.runId,
              formatWhen(run.startedAt),
              took !== undefined
                ? `${formatDuration(took)}${run.status === "running" ? " so far" : ""}`
                : undefined,
              tokens !== undefined ? `${formatCount(tokens)} tokens` : undefined,
            ]
              .filter(Boolean)
              .join(" · ")}
            note={runNote(run)}
            action={
              run.runId ? (
                <Button asChild size="28" variant="ghost">
                  <Link
                    to={`/i/${encodeURIComponent(instance)}/traces?run_id=${encodeURIComponent(run.runId)}`}
                  >
                    View trace
                  </Link>
                </Button>
              ) : undefined
            }
          />
        );
      })}
    </div>
  );
}

function summaryOf(session: SessionDetail): { text?: string | undefined; topics: string[] } {
  const raw = (session as { session_summary?: unknown }).session_summary;
  if (typeof raw === "string") return { text: raw, topics: [] };
  if (typeof raw === "object" && raw !== null) {
    const value = raw as { summary?: unknown; topics?: unknown };
    return {
      text: typeof value.summary === "string" ? value.summary : undefined,
      topics: Array.isArray(value.topics) ? value.topics.map(String) : [],
    };
  }
  return { topics: [] };
}

function MetricsTab({ session, runs }: { session: SessionDetail; runs: readonly RunState[] }) {
  const metrics = ((session as { metrics?: unknown }).metrics ?? {}) as Record<string, unknown>;
  const number = (key: string) => (typeof metrics[key] === "number" ? metrics[key] : undefined);
  const runTime = runs.reduce((total, run) => total + (duration(run) ?? 0), 0);
  const toolCalls = runs.reduce((total, run) => total + run.tools.length, 0);
  const model =
    runs.map((run) => run.model).find(Boolean) ??
    (typeof metrics.model === "string" ? metrics.model : undefined);
  const tiles: [string, string][] = [
    ["Input tokens", formatCount(number("input_tokens"))],
    ["Output tokens", formatCount(number("output_tokens"))],
    ["Total tokens", formatCount(number("total_tokens") ?? runTokens(metrics))],
    ["Run time", runTime ? formatDuration(runTime) : "—"],
    ["Tool calls", formatCount(toolCalls)],
    ["Model", model ?? "—"],
  ];
  return (
    <dl className="grid grid-cols-2 gap-2">
      {tiles.map(([label, value]) => (
        <div key={label} className="flex flex-col rounded-tile border border-border bg-surface px-3 py-2.5">
          <dt className="text-[12px] text-fg-muted">{label}</dt>
          <dd className="truncate text-[15px] font-semibold tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SessionDetailPanel({
  instance,
  sessionId,
  tab,
  onTab,
  onClose,
  onForked,
  onDeleted,
}: {
  instance: string;
  sessionId: string;
  tab: Tab;
  onTab: (tab: Tab) => void;
  onClose: () => void;
  onForked: (sessionId: string, owner: Owner) => void;
  onDeleted: () => void;
}) {
  const session = useSession(instance, sessionId);
  const owner = session.data ? ownerOf(session.data) : undefined;
  const runs = useSessionRuns(
    instance,
    sessionId,
    owner ? { agents: "agent", teams: "team", workflows: "workflow" }[owner.family] : undefined,
  );
  const actions = useSessionActions(instance);
  const canEditState = useCan("sessions:write", instance).allowed === true;
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState("");
  const states = (runs.data ?? [])
    .filter((run) => !("parent_run_id" in run && run.parent_run_id))
    .map((run) => fromStoredRun(run, sessionId));

  if (session.isPending) {
    return (
      <aside
        aria-label="Session detail"
        className="flex w-[480px] shrink-0 flex-col gap-3 border-l border-border-subtle p-5"
      >
        <LoadingRows rows={6} label="Loading session" />
      </aside>
    );
  }
  if (session.isError) {
    return (
      <aside
        aria-label="Session detail"
        className="flex w-[480px] shrink-0 flex-col gap-3 border-l border-border-subtle p-5"
      >
        <ErrorState {...describeError(session.error)} onRetry={() => void session.refetch()} />
      </aside>
    );
  }
  const data = session.data;
  const summary = summaryOf(data);
  const encoded = encodeURIComponent(sessionId);

  return (
    <aside
      aria-label="Session detail"
      className="flex w-[480px] shrink-0 flex-col gap-4 overflow-y-auto border-l border-border-subtle p-5"
    >
      <header className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-[15px] font-semibold break-all">{data.session_name || data.session_id}</h2>
          <Button variant="icon" size="28" aria-label="Close session" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>
        <p className="font-mono text-[11.5px] text-fg-muted">
          {[data.session_id, owner?.id, data.user_id, `started ${formatWhen(data.created_at)}`]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {owner && owner.family !== "workflows" && (
            <PermissionGate scope={`${owner.family}:run`} instance={instance}>
              <ApiHint
                call={`POST /${owner.family}/${owner.id}/sessions/${sessionId}/fork`}
                scope={`${owner.family}:run`}
              >
                <Button
                  size="30"
                  variant="outline"
                  disabled={actions.fork.isPending}
                  onClick={() => {
                    actions.fork.mutate(
                      { sessionId, family: owner.family as "agents" | "teams", componentId: owner.id },
                      {
                        onSuccess: (forked) => {
                          if (forked.session_id) onForked(forked.session_id, owner);
                        },
                      },
                    );
                  }}
                >
                  Fork session
                </Button>
              </ApiHint>
            </PermissionGate>
          )}
          <PermissionGate scope="sessions:write" instance={instance}>
            <ApiHint call={`POST /sessions/${encoded}/rename`} scope="sessions:write">
              <Button
                size="30"
                variant="outline"
                onClick={() => {
                  setName(data.session_name);
                  setRenaming(true);
                }}
              >
                Rename
              </Button>
            </ApiHint>
          </PermissionGate>
          <PermissionGate scope="sessions:delete" instance={instance}>
            <ApiHint call={`DELETE /sessions/${encoded}`} scope="sessions:delete">
              <Button
                size="30"
                variant="destructive-outline"
                disabled={actions.remove.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      `Delete ${data.session_name || data.session_id} and its runs? This can't be undone.`,
                    )
                  ) {
                    actions.remove.mutate({ sessionId }, { onSuccess: onDeleted });
                  }
                }}
              >
                Delete
              </Button>
            </ApiHint>
          </PermissionGate>
        </div>
        <p className="font-mono text-[11px] text-fg-faint">
          fork · {owner?.family ?? "agents"}:run &nbsp; rename · sessions:write &nbsp; delete ·
          sessions:delete
        </p>
        {renaming && (
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              actions.rename.mutate(
                { sessionId, name: name.trim() },
                {
                  onSuccess: () => {
                    setRenaming(false);
                  },
                },
              );
            }}
          >
            <input
              aria-label="Session name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
              className="h-8 flex-1 rounded-control border border-border-input bg-surface px-2.5 text-[13px]"
            />
            <Button
              type="submit"
              size="30"
              variant="primary"
              disabled={!name.trim() || actions.rename.isPending}
            >
              Save
            </Button>
            <Button
              size="30"
              variant="ghost"
              onClick={() => {
                setRenaming(false);
              }}
            >
              Cancel
            </Button>
          </form>
        )}
        {(actions.fork.isError || actions.rename.isError || actions.remove.isError) && (
          <Callout tone="danger">
            {describeError(actions.fork.error ?? actions.rename.error ?? actions.remove.error).reason}
          </Callout>
        )}
      </header>

      <Tabs
        value={tab}
        onValueChange={(value) => {
          onTab(value as Tab);
        }}
      >
        <TabsList>
          {TABS.map((item) => (
            <TabsTrigger key={item.id} value={item.id}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="chat" className="pt-4">
          {runs.isPending ? (
            <LoadingRows rows={4} label="Loading runs" />
          ) : (
            <ChatTab instance={instance} runs={states} />
          )}
        </TabsContent>
        <TabsContent value="runs" className="pt-4">
          {runs.isPending ? (
            <LoadingRows rows={4} label="Loading runs" />
          ) : (
            <RunsTab instance={instance} runs={states} />
          )}
        </TabsContent>
        <TabsContent value="files" className="pt-4">
          <SessionArtifacts instance={instance} sessionId={sessionId} />
        </TabsContent>
        <TabsContent value="summary" className="flex flex-col gap-2 pt-4">
          {summary.topics.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {summary.topics.map((topic) => (
                <span
                  key={topic}
                  className="rounded-badge border border-border-strong px-1.5 py-0.5 text-[11.5px] text-fg-secondary"
                >
                  {topic}
                </span>
              ))}
            </div>
          )}
          {summary.text ? (
            <>
              <p className="text-[13.5px] text-fg-prose">{summary.text}</p>
              <Provenance>
                Written by the session summary manager after run {String(states.length)}.
              </Provenance>
            </>
          ) : (
            <EmptyState title="No summary yet">
              Summaries appear when the component enables the session summary manager.
            </EmptyState>
          )}
        </TabsContent>
        <TabsContent value="state" className="pt-4">
          {canEditState ? (
            <JsonEditor
              label="session_state · editable with sessions:write"
              value={data.session_state ?? {}}
              saving={actions.updateState.isPending}
              onSave={(state) => {
                actions.updateState.mutate({ sessionId, state });
              }}
              footer={
                actions.updateState.isError ? (
                  <span className="text-[12px] text-danger">
                    {describeError(actions.updateState.error).reason}
                  </span>
                ) : actions.updateState.isSuccess ? (
                  <span className="text-[12px] text-fg-muted">Saved.</span>
                ) : undefined
              }
            />
          ) : (
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] text-fg-muted">session_state · editable with sessions:write</span>
              <JsonView value={data.session_state ?? {}} label="session_state" />
            </div>
          )}
        </TabsContent>
        <TabsContent value="metrics" className="pt-4">
          <MetricsTab session={data} runs={states} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
