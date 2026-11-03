// Inline approvals in a paused run: find the pending approval for the run, decide it through the
// control plane (resolve + continue with delegated elevation, audited with the args diff), then replay the run so the
// continuation streams in.
import {
  approvalsDecideMutation,
  describeError,
  gatewayJson,
  type AgentOS,
  type DecideOut,
} from "@agnostic/api";
import { formatRelative, useCan, type ToolCall } from "@agnostic/core";
import { ApprovalCard, Callout } from "@agnostic/ui";
import { skipToken, useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

type Approval = AgentOS.ApprovalResponse;

/** Pending approvals of the run (and its member runs, for teams), oldest first. */
function useRunApprovals(instance: string, runIds: readonly string[], enabled: boolean) {
  return useQuery({
    queryKey: [instance, "agentos", "approvals", "run", runIds],
    queryFn:
      enabled && runIds.length > 0
        ? async () => {
            const pages = await Promise.all(
              runIds.map((runId) =>
                gatewayJson<AgentOS.PaginatedResponseApprovalResponse>(
                  instance,
                  `approvals?run_id=${encodeURIComponent(runId)}&status=pending&limit=20`,
                ),
              ),
            );
            return pages
              .flatMap((page) => page.data)
              .sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
          }
        : skipToken,
    retry: false,
    staleTime: 0,
  });
}

function outcomeText(result: DecideOut): string {
  if (result.already_resolved) return `Someone already ${result.status} this request.`;
  const verb = result.status === "approved" ? "Approved" : "Rejected";
  const edited = result.args_changed.length ? ` with edited ${result.args_changed.join(", ")}` : "";
  switch (result.continue_state) {
    case "continued":
      return `${verb}${edited} · the run is continuing.`;
    case "pending_admin":
      return `${verb}${edited} · the run waits for an admin approval: ${result.continue_detail ?? ""}`;
    case "conflict":
      return `${verb}${edited} · another continuation owns the run; it resumes when that finishes.`;
    case "failed":
      return `${verb}${edited}, but the run didn't continue: ${result.continue_detail ?? "unknown error"}.`;
    default:
      return `${verb}${edited}.`;
  }
}

function ApprovalItem({
  instance,
  instanceName,
  approval,
  onContinued,
}: {
  instance: string;
  instanceName: string;
  approval: Approval;
  onContinued: () => void;
}) {
  const can = useCan("approvals:write", instance);
  const [result, setResult] = useState<DecideOut | undefined>();
  const decide = useMutation({
    ...approvalsDecideMutation(),
    onSuccess: (data) => {
      setResult(data);
      // The run continues in the background on the instance: replay it from the start to stream the rest.
      if (data.continue_state === "continued") onContinued();
    },
  });
  const run = (decision: "approve" | "reject", edited?: Record<string, unknown>, note?: string) => {
    decide.mutate({
      path: { instance, approval_id: approval.id },
      body: { decision, ...(edited ? { edited_args: edited } : {}), ...(note ? { note } : {}) },
    });
  };
  return (
    <div className="flex flex-col gap-2">
      <ApprovalCard
        toolName={approval.tool_name ?? approval.source_name ?? "step"}
        args={approval.tool_args ?? {}}
        requested={approval.created_at ? `requested ${formatRelative(approval.created_at)}` : undefined}
        canDecide={can.allowed === true}
        cannotDecideReason={`Waiting for someone with approvals:write on ${instanceName}.`}
        busy={decide.isPending}
        onApprove={(edited) => {
          run("approve", edited);
        }}
        rejectNeedsNote
        onReject={(note) => {
          run("reject", undefined, note);
        }}
        outcome={result ? outcomeText(result) : undefined}
        footer={
          can.allowed ? (
            <>
              Shown because you hold <code className="font-mono">approvals:write</code> on {instanceName}
            </>
          ) : undefined
        }
      />
      {decide.isError && (
        <Callout tone="danger" title="The decision didn't go through">
          {describeError(decide.error).reason}
        </Callout>
      )}
    </div>
  );
}

/** Approvals blocking this run, or a direct confirmation when the paused tools have no approval record. */
export function RunApprovals({
  instance,
  instanceName,
  onContinued,
  runIds,
  pausedTools,
  onConfirmDirectly,
}: {
  instance: string;
  instanceName: string;
  onContinued: () => void;
  runIds: readonly string[];
  pausedTools: readonly ToolCall[];
  onConfirmDirectly: (tool: ToolCall, confirmed: boolean, edited?: Record<string, unknown>) => void;
}) {
  const canRead = useCan("approvals:read", instance);
  const approvals = useRunApprovals(instance, runIds, canRead.allowed === true);
  if (approvals.data && approvals.data.length > 0) {
    return (
      <>
        {approvals.data.map((approval) => (
          <ApprovalItem
            key={approval.id}
            instance={instance}
            instanceName={instanceName}
            approval={approval}
            onContinued={onContinued}
          />
        ))}
      </>
    );
  }
  if (approvals.isPending && canRead.allowed) return null;
  // No approval record (a plain `requires_confirmation` tool, or approvals disabled): the run owner confirms by continuing.
  return (
    <>
      {pausedTools.map((tool) => (
        <ApprovalCard
          key={tool.id}
          toolName={tool.name}
          args={tool.args}
          canDecide
          onApprove={(edited) => {
            onConfirmDirectly(tool, true, edited);
          }}
          onReject={() => {
            onConfirmDirectly(tool, false);
          }}
          footer="The tool asks for confirmation before it runs."
        />
      ))}
    </>
  );
}
