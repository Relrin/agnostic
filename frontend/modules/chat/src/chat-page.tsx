import { describeError } from "@agnostic/api";
import {
  RunView,
  SESSION_TYPE,
  agentosKeys,
  dayGroup,
  findInstance,
  formatRelative,
  fromStoredRun,
  isSettled,
  restoreRuns,
  startRun,
  toDate,
  useCan,
  useComponentVersions,
  useComponents,
  useInstances,
  useRunStream,
  useRunStreams,
  useSession,
  useSessionActions,
  useSessionRuns,
  useSessions,
  useTourFromSearch,
  type ComponentSummary,
  type RunFamily,
  type RunStream,
  type RunTarget,
  type StoredRun,
} from "@agnostic/core";
import {
  Button,
  Composer,
  EmptyState,
  EntitySquare,
  ErrorState,
  LoadingRows,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SessionList,
  Tour,
  type AttachmentRule,
  type TourStep,
} from "@agnostic/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { PanelRight, Plus } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { SessionRail } from "./session-rail";

const FAMILIES: readonly { value: RunFamily; label: string; kind: "agent" | "team" | "workflow" }[] = [
  { value: "agents", label: "Agents", kind: "agent" },
  { value: "teams", label: "Agent teams", kind: "team" },
  { value: "workflows", label: "Workflows", kind: "workflow" },
];

/** Attachment limits (04 §3.3): what AgentOS media handling accepts without a custom reader. */
export const ATTACHMENTS: AttachmentRule = {
  maxBytes: 20 * 1024 * 1024,
  maxFiles: 5,
  accept: [
    "image/*",
    "audio/*",
    "video/*",
    "application/pdf",
    "text/*",
    ".csv",
    ".json",
    ".md",
    ".docx",
    ".xlsx",
  ],
};

const TOUR: TourStep[] = [
  {
    target: "chat-target",
    title: "Pick who to talk to",
    body: "Choose an agent, agent team or workflow on this instance, and the version to run (drafts for admins).",
  },
  {
    target: "chat-composer",
    title: "Send a message",
    body: "Enter sends, Shift+Enter adds a line. The run streams in with its tool calls; approvals you can decide appear inline.",
  },
  {
    target: "chat-sessions",
    title: "Pick up where you left off",
    body: "Every conversation is a session on the instance. Open one to continue it, or start a new session.",
  },
];

function isFamily(value: string | undefined): value is RunFamily {
  return value === "agents" || value === "teams" || value === "workflows";
}

export function chatPath(
  instance: string,
  family: RunFamily,
  componentId?: string,
  sessionId?: string,
): string {
  let path = `/i/${encodeURIComponent(instance)}/chat/${family}`;
  if (componentId) path += `/${encodeURIComponent(componentId)}`;
  if (componentId && sessionId) path += `/${encodeURIComponent(sessionId)}`;
  return path;
}

type VersionOption = { value: string; label: string; version: number | undefined };

function useVersionOptions(instance: string, component: ComponentSummary | undefined) {
  const canSeeDrafts = useCan("agent_os:admin", instance).allowed === true;
  const versions = useComponentVersions(instance, component?.id, component?.isComponent === true);
  return useMemo((): VersionOption[] => {
    if (!component) return [];
    const current = component.currentVersion;
    if (!component.isComponent || !versions.data) {
      return [
        {
          value: "current",
          label: current !== undefined ? `v${String(current)} · current` : "code",
          version: undefined,
        },
      ];
    }
    return versions.data
      .filter((item) => item.stage !== "draft" || canSeeDrafts)
      .map((item) => ({
        value: String(item.version),
        version: item.version === current ? undefined : item.version,
        label:
          item.stage === "draft"
            ? `Draft v${String(item.version)}`
            : item.version === current
              ? `v${String(item.version)} · current`
              : `v${String(item.version)}`,
      }));
  }, [canSeeDrafts, component, versions.data]);
}

/** A live run of this conversation: re-renders on every event, and tells the page when it learns its session. */
function LiveRun({
  stream,
  target,
  instanceName,
  componentName,
  versionLabel,
  onSession,
  onSettled,
  onRetry,
}: {
  stream: RunStream;
  target: RunTarget;
  instanceName: string;
  componentName: string;
  versionLabel: string | undefined;
  onSession: (sessionId: string) => void;
  onSettled: () => void;
  onRetry: (message: string) => void;
}) {
  const state = useRunStream(stream);
  const sessionId = state?.sessionId;
  const settled = state ? isSettled(state) : false;
  useEffect(() => {
    if (sessionId) onSession(sessionId);
  }, [onSession, sessionId]);
  useEffect(() => {
    if (settled) onSettled();
  }, [onSettled, settled]);
  if (!state) return null;
  const input = state.input;
  return (
    <>
      <RunView
        state={state}
        stream={stream}
        target={target}
        instanceName={instanceName}
        componentName={componentName}
        versionLabel={versionLabel}
        onRetry={
          input
            ? () => {
                onRetry(input);
              }
            : undefined
        }
      />
      <span aria-live="polite" className="sr-only">
        {state.status === "running" ? "Run in progress" : `Run ${state.status}`}
      </span>
    </>
  );
}

/** `/i/:instance/chat/:kind/:componentId/:sessionId?version=` (design spec A §2). */
export function ChatPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const instanceRef = params.instance ?? "";
  const family: RunFamily = isFamily(params.kind) ? params.kind : "agents";
  const componentId = params.componentId;
  const sessionId = params.sessionId;
  const instances = useInstances();
  const instance = findInstance(instances.data, instanceRef);
  const instanceName = instance?.display_name ?? instanceRef;

  const components = useComponents(instanceRef, family);
  const component = components.data?.find((item) => item.id === componentId);
  useEffect(() => {
    const first = components.data?.[0];
    // Keeps `?tour=` so a tour opened from Home survives the jump to the first component.
    if (!componentId && first)
      void navigate({
        to: chatPath(instanceRef, family, first.id),
        search: typeof search.tour === "string" ? { tour: search.tour } : {},
        replace: true,
      });
  }, [componentId, components.data, family, instanceRef, navigate, search.tour]);
  const tour = useTourFromSearch("chat");

  const versionOptions = useVersionOptions(instanceRef, component);
  const requested =
    typeof search.version === "number" || typeof search.version === "string"
      ? String(search.version)
      : undefined;
  const selectedVersion =
    versionOptions.find((option) => option.value === requested) ??
    versionOptions.find((option) => option.version === undefined) ??
    versionOptions[0];
  const versionLabel = selectedVersion?.label.replace(" · current", "");

  const [showDetails, setShowDetails] = useState(true);
  const [sessionSearch, setSessionSearch] = useState("");
  const deferredSearch = useDeferredValue(sessionSearch);
  const sessions = useSessions(
    instanceRef,
    { type: SESSION_TYPE[family], componentId, name: deferredSearch || undefined, limit: 50 },
    componentId !== undefined,
  );
  const session = useSession(instanceRef, sessionId, SESSION_TYPE[family]);
  const runs = useSessionRuns(instanceRef, sessionId, SESSION_TYPE[family]);
  const actions = useSessionActions(instanceRef);

  const target: RunTarget | undefined = componentId
    ? { instance: instanceRef, family, componentId }
    : undefined;
  const streams = useRunStreams();
  const [pendingKey, setPendingKey] = useState<string | undefined>();
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !instanceRef) return;
    restored.current = true;
    restoreRuns(instanceRef);
  }, [instanceRef]);

  const liveStreams = Object.values(streams).filter((stream) => {
    if (!target || stream.target.instance !== instanceRef || stream.target.componentId !== componentId)
      return false;
    const state = stream.getState();
    return stream.key === pendingKey || (sessionId !== undefined && state.sessionId === sessionId);
  });
  const liveRunIds = new Set(liveStreams.map((stream) => stream.getState().runId).filter(Boolean));
  const history = (runs.data ?? []).filter(
    (run) => !liveRunIds.has(run.run_id) && !("parent_run_id" in run && run.parent_run_id),
  );
  const latest = liveStreams.map((stream) => stream.getState()).find((state) => !isSettled(state));
  const streaming = latest !== undefined;

  const groups = useMemo(() => {
    const byGroup = new Map<string, { id: string; name: string; meta: string }[]>();
    for (const item of sessions.data?.data ?? []) {
      const when = toDate(item.updated_at ?? item.created_at) ?? new Date(0);
      const label = dayGroup(when);
      const list = byGroup.get(label) ?? [];
      list.push({
        id: item.session_id,
        name: item.session_name || item.session_id,
        meta: `${item.user_id ?? "—"} · ${formatRelative(when)}`,
      });
      byGroup.set(label, list);
    }
    return [...byGroup.entries()].map(([label, items]) => ({ label, items }));
  }, [sessions.data]);

  const send = (message: string, files: File[]) => {
    if (!target) return;
    const stream = startRun(target, { message, sessionId, version: selectedVersion?.version, files });
    if (!sessionId) setPendingKey(stream.key);
  };

  const onSession = (id: string) => {
    if (!sessionId && componentId) {
      void navigate({
        to: chatPath(instanceRef, family, componentId, id),
        search: requested ? { version: requested } : {},
        replace: true,
      });
    }
  };
  const onSettled = () => {
    void queryClient.invalidateQueries({ queryKey: agentosKeys.all(instanceRef) });
  };
  const fork = () => {
    if (!sessionId || !componentId || family === "workflows") return;
    actions.fork.mutate(
      { sessionId, family, componentId },
      {
        onSuccess: (forked) => {
          if (forked.session_id)
            void navigate({ to: chatPath(instanceRef, family, componentId, forked.session_id) });
        },
      },
    );
  };

  const componentName = component?.name ?? componentId ?? "";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="sr-only">{componentName ? `Chat with ${componentName}` : "Chat"}</h1>
      <Tour label="Chat" steps={TOUR} open={tour.open && componentId !== undefined} onEnd={tour.close} />
      <div
        role="toolbar"
        aria-label="Chat target"
        data-tour="chat-target"
        className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-6 py-2.5"
      >
        <SegmentedControl
          label="Component type"
          value={family}
          onValueChange={(value) => {
            void navigate({ to: chatPath(instanceRef, value) });
          }}
          options={FAMILIES.map((item) => ({
            value: item.value,
            label: item.label,
            icon: <EntitySquare kind={item.kind} />,
          }))}
        />
        <Select
          value={componentId ?? ""}
          onValueChange={(value) => {
            void navigate({ to: chatPath(instanceRef, family, value) });
          }}
        >
          <SelectTrigger aria-label="Component" className="h-8 w-56 font-mono text-[12.5px]">
            <SelectValue placeholder={components.isPending ? "Loading…" : "Choose"} />
          </SelectTrigger>
          <SelectContent>
            {(components.data ?? []).map((item) => (
              <SelectItem key={item.id} value={item.id} className="font-mono">
                {item.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {versionOptions.length > 0 && selectedVersion && (
          <Select
            value={selectedVersion.value}
            onValueChange={(value) => {
              const option = versionOptions.find((item) => item.value === value);
              if (componentId) {
                void navigate({
                  to: chatPath(instanceRef, family, componentId),
                  search: option?.version !== undefined ? { version: option.version } : {},
                });
              }
            }}
          >
            <SelectTrigger aria-label="Version" className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {versionOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="32"
            aria-pressed={showDetails}
            disabled={!sessionId}
            onClick={() => {
              setShowDetails(!showDetails);
            }}
          >
            <PanelRight aria-hidden />
            Session details
          </Button>
          <Button
            variant="primary"
            size="32"
            disabled={!componentId}
            onClick={() => {
              setPendingKey(undefined);
              if (componentId) void navigate({ to: chatPath(instanceRef, family, componentId) });
            }}
          >
            <Plus aria-hidden />
            New session
          </Button>
        </div>
      </div>

      {components.isError ? (
        <div className="p-6">
          <ErrorState
            {...describeError(components.error)}
            onRetry={() => {
              void components.refetch();
            }}
          />
        </div>
      ) : components.data?.length === 0 ? (
        <div className="p-6">
          <EmptyState
            title={`No ${FAMILIES.find((item) => item.value === family)?.label.toLowerCase() ?? "components"} you can run on ${instanceName}`}
          >
            They appear here once they're registered on the instance and you hold a run grant for them. Ask an
            administrator, or build one in Studio.
          </EmptyState>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div
            data-tour="chat-sessions"
            className="flex w-64 shrink-0 flex-col border-r border-border-subtle px-3 py-3"
          >
            {sessions.isPending && componentId ? (
              <LoadingRows rows={6} label="Loading sessions" />
            ) : (
              <SessionList
                label={`Sessions for ${componentId ?? ""}`}
                groups={groups}
                selectedId={sessionId}
                search={sessionSearch}
                onSearch={setSessionSearch}
                onSelect={(id) => {
                  setPendingKey(undefined);
                  if (componentId) void navigate({ to: chatPath(instanceRef, family, componentId, id) });
                }}
                footer={
                  groups.length === 0 ? (
                    <p className="px-2 text-[12.5px] text-fg-muted">
                      {deferredSearch
                        ? "No sessions match."
                        : "No sessions yet. Send a message to start one."}
                    </p>
                  ) : undefined
                }
              />
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              <div className="mx-auto flex max-w-3xl flex-col gap-6">
                {sessionId && runs.isPending && <LoadingRows rows={4} label="Loading conversation" />}
                {sessionId && runs.isError && <ErrorState {...describeError(runs.error)} />}
                {target &&
                  history.map((run: StoredRun) => (
                    <RunView
                      key={run.run_id}
                      state={fromStoredRun(run, sessionId)}
                      stream={undefined}
                      target={target}
                      instanceName={instanceName}
                      componentName={componentName}
                      versionLabel={versionLabel}
                      onFork={family === "workflows" ? undefined : fork}
                    />
                  ))}
                {target &&
                  liveStreams.map((stream) => (
                    <LiveRun
                      key={stream.key}
                      stream={stream}
                      target={target}
                      instanceName={instanceName}
                      componentName={componentName}
                      versionLabel={versionLabel}
                      onSession={onSession}
                      onSettled={onSettled}
                      onRetry={(message) => {
                        send(message, []);
                      }}
                    />
                  ))}
                {!sessionId && liveStreams.length === 0 && componentId && (
                  <EmptyState title={`Start a conversation with ${componentName}`}>
                    Runs stream here with their tool calls. Approvals you can decide show up inline.
                  </EmptyState>
                )}
              </div>
            </div>
            <div className="border-t border-border-subtle px-6 py-3">
              <div className="mx-auto max-w-3xl" data-tour="chat-composer">
                <Composer
                  label={`Message ${componentName}`}
                  placeholder={`Message ${componentName}${versionLabel ? ` ${versionLabel}` : ""}…`}
                  streaming={streaming}
                  disabled={!componentId}
                  attachments={family === "workflows" ? undefined : ATTACHMENTS}
                  members={family === "teams" ? component?.members : undefined}
                  onSend={send}
                  onStop={() => {
                    const live = liveStreams.find((stream) => !isSettled(stream.getState()));
                    void live?.cancel();
                  }}
                />
              </div>
            </div>
          </div>

          {showDetails && sessionId && session.data && (
            <SessionRail
              instance={instanceRef}
              session={session.data}
              runs={runs.data ?? []}
              onClose={() => {
                setShowDetails(false);
              }}
              onDeleted={() => {
                if (componentId) void navigate({ to: chatPath(instanceRef, family, componentId) });
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
