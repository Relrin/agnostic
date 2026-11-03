// Requests: temporary access people asked for. Approvers (Owners, Administrators, group owners) approve with an
// optional note, which creates a binding that expires, or deny; people withdraw their own pending requests.
import {
  accessApproveRequestMutation,
  accessCancelRequestMutation,
  accessDenyRequestMutation,
  accessListRequestsOptions,
  describeError,
  type AccessRequestOut,
} from "@agnostic/api";
import { STALE_TIME, formatRelative, useMe, withQueryFn } from "@agnostic/core";
import {
  AccessChip,
  Avatar,
  Button,
  Callout,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Field,
  LoadingRows,
  SegmentedControl,
  StatusPill,
  Textarea,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  findInstance,
  grantName,
  memberName,
  refreshDirectory,
  roleColor,
  type Directory,
  type PeopleSearch,
} from "./people-api";

export function useRequests(all: boolean) {
  return useQuery({
    ...withQueryFn(accessListRequestsOptions(all ? {} : { query: { status: "pending" } })),
    staleTime: STALE_TIME.list,
    retry: false,
  });
}

function hours(value: number): string {
  if (value >= 24 && value % 24 === 0) return `${String(value / 24)} d`;
  return `${String(value)} h`;
}

function RequestGrant({ request, directory }: { request: AccessRequestOut; directory: Directory }) {
  const instance = findInstance(directory.allInstances, request.instance_id);
  return (
    <AccessChip
      roleName={grantName(request, directory.allRoles)}
      color={roleColor(request.role_id, directory.allRoles)}
      instance={instance?.slug ?? null}
      env={instance?.env_tag ?? null}
    />
  );
}

type Decision = { request: AccessRequestOut; verb: "approve" | "deny" };

function DecisionDialog({
  decision,
  directory,
  onClose,
}: {
  decision: Decision;
  directory: Directory;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const { request, verb } = decision;
  const name = memberName(directory.allMembers, request.requester_id);
  const onSuccess = async () => {
    toast.success(
      verb === "approve"
        ? `Approved: ${name} has access for ${hours(request.duration_hours)}`
        : `Denied ${name}'s request`,
    );
    onClose();
    await refreshDirectory(client);
  };
  const approve = useMutation({ ...accessApproveRequestMutation(), onSuccess });
  const deny = useMutation({ ...accessDenyRequestMutation(), onSuccess });
  const mutation = verb === "approve" ? approve : deny;
  const label = verb === "approve" ? "Approve" : "Deny";
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {label} {name}'s request?
          </DialogTitle>
          <DialogDescription>
            {verb === "approve"
              ? `Creates a binding that expires after ${hours(request.duration_hours)}. ${name} and the audit log see your note.`
              : `${name} sees your note; nothing changes in their access.`}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <RequestGrant request={request} directory={directory} />
            <span className="text-fg-secondary">“{request.reason}”</span>
          </div>
          <Field label="Note (optional)">
            {({ id }) => (
              <Textarea
                id={id}
                rows={2}
                value={note}
                onChange={(event) => {
                  setNote(event.target.value);
                }}
              />
            )}
          </Field>
          {mutation.error && <Callout tone="danger">{describeError(mutation.error).reason}</Callout>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={verb === "approve" ? "primary" : "destructive-outline"}
            disabled={mutation.isPending}
            onClick={() => {
              mutation.mutate({ path: { request_id: request.id }, body: { note: note.trim() || null } });
            }}
          >
            {label}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RequestsTab({
  directory,
  state,
  go,
}: {
  directory: Directory;
  state: PeopleSearch;
  go: (next: Partial<PeopleSearch>) => void;
}) {
  const client = useQueryClient();
  const me = useMe();
  const all = state.requests === "all";
  const requests = useRequests(all);
  const [decision, setDecision] = useState<Decision | undefined>(undefined);
  const cancel = useMutation({
    ...accessCancelRequestMutation(),
    onSuccess: async () => {
      toast.success("Withdrew your request");
      await refreshDirectory(client);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  const columns: Column<AccessRequestOut>[] = [
    {
      id: "requester",
      header: "Requester",
      cell: (request) => {
        const name = memberName(directory.allMembers, request.requester_id);
        return (
          <span className="flex items-center gap-2">
            <Avatar id={request.requester_id} name={name} size={24} />
            <span className="font-medium">{name}</span>
          </span>
        );
      },
    },
    {
      id: "grant",
      header: "Asks for",
      cell: (request) => <RequestGrant request={request} directory={directory} />,
    },
    {
      id: "duration",
      header: "For",
      cell: (request) => <span className="tabular-nums">{hours(request.duration_hours)}</span>,
    },
    {
      id: "reason",
      header: "Reason",
      cell: (request) => <span className="text-fg-secondary">{request.reason}</span>,
    },
    {
      id: "age",
      header: "Asked",
      cell: (request) => (
        <span className="whitespace-nowrap text-fg-secondary">{formatRelative(request.created_at)}</span>
      ),
    },
    ...(all
      ? [
          {
            id: "status",
            header: "Status",
            cell: (request: AccessRequestOut) => <StatusPill status={request.status} />,
          },
        ]
      : []),
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (request) => {
        if (request.status !== "pending") return null;
        const name = memberName(directory.allMembers, request.requester_id);
        return (
          <span className="inline-flex gap-1">
            {request.can_decide && (
              <>
                <Button
                  size="28"
                  variant="outline"
                  aria-label={`Approve ${name}'s request`}
                  onClick={() => {
                    setDecision({ request, verb: "approve" });
                  }}
                >
                  Approve
                </Button>
                <Button
                  size="28"
                  variant="destructive-text"
                  aria-label={`Deny ${name}'s request`}
                  onClick={() => {
                    setDecision({ request, verb: "deny" });
                  }}
                >
                  Deny
                </Button>
              </>
            )}
            {request.requester_id === me.data?.id && (
              <Button
                size="28"
                variant="ghost"
                disabled={cancel.isPending}
                onClick={() => {
                  cancel.mutate({ path: { request_id: request.id } });
                }}
              >
                Cancel request
              </Button>
            )}
          </span>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-fg-secondary">
          Approving creates a binding that expires on its own; every step is in the audit log.
        </p>
        <SegmentedControl
          label="Requests to show"
          value={all ? "all" : "pending"}
          options={[
            { value: "pending", label: "Pending" },
            { value: "all", label: "All" },
          ]}
          onValueChange={(value) => {
            go({ requests: value === "all" ? "all" : undefined });
          }}
        />
      </div>
      {requests.isPending ? (
        <LoadingRows rows={2} label="Loading requests" />
      ) : requests.isError ? (
        <ErrorState {...describeError(requests.error)} onRetry={() => void requests.refetch()} />
      ) : requests.data.length === 0 ? (
        <EmptyState title={all ? "No access requests yet." : "Nothing is waiting for a decision."}>
          People ask for temporary access from any “Why can't I?” explanation.
        </EmptyState>
      ) : (
        <div className="min-w-0 overflow-x-auto">
          <div className="min-w-[760px]">
            <DataTable
              label="Access requests"
              columns={columns}
              rows={requests.data}
              rowKey={(request) => request.id}
            />
          </div>
        </div>
      )}
      {decision && (
        <DecisionDialog
          key={decision.request.id + decision.verb}
          decision={decision}
          directory={directory}
          onClose={() => {
            setDecision(undefined);
          }}
        />
      )}
    </div>
  );
}
