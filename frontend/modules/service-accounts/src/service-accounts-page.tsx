// Service accounts: machine principals (CI, chat bridges, bots) with native AgentOS tokens per instance and gateway
// tokens. The table lists them; the selected one (`?account=<name>`) opens in an aside.
import { describeError, serviceAccountsListAccountsOptions, type ServiceAccountOut } from "@agnostic/api";
import { PermissionGate, STALE_TIME, formatCount, formatRelative, withQueryFn } from "@agnostic/core";
import {
  ApiHint,
  Avatar,
  Button,
  Callout,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingRows,
  PageIntro,
  cn,
  type Column,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useState } from "react";

import { AccountDetail } from "./account-detail";
import { CreateAccountSheet } from "./create-account";
import { InstanceChips } from "./parts";
import { expiryState, readAccount } from "./service-accounts-api";

const PATH = "/access/service-accounts";

function ExpiryCell({ row }: { row: ServiceAccountOut }) {
  const state = expiryState(row);
  return (
    <span
      className={cn(
        "whitespace-nowrap",
        state.tone === "danger" && "text-danger",
        state.tone === "warning" && "text-warning",
        state.tone === "normal" && "text-fg-secondary",
      )}
    >
      {state.text}
    </span>
  );
}

/** `/access/service-accounts?account=<name>`. */
export function ServiceAccountsPage() {
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const selected = readAccount(search);
  const [creating, setCreating] = useState(false);
  const open = (account: string | undefined) => {
    void navigate({ to: PATH, search: account ? { account } : {} });
  };

  const list = useQuery({
    ...withQueryFn(serviceAccountsListAccountsOptions()),
    staleTime: STALE_TIME.list,
  });
  const rows = list.data ?? [];

  const columns: Column<ServiceAccountOut>[] = [
    {
      id: "account",
      header: "Account",
      cell: (row) => (
        <div className="flex items-center gap-2.5">
          <Avatar id={row.id} name={row.name} kind="machine" size={26} />
          <div className="flex min-w-0 flex-col gap-0.5">
            <button
              type="button"
              className="cursor-pointer self-start text-left font-medium text-fg hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                open(row.name);
              }}
            >
              {row.name}
            </button>
            <code className="font-mono text-[11.5px] text-fg-muted">{row.principal}</code>
          </div>
        </div>
      ),
    },
    {
      id: "scopes",
      header: "Scopes",
      cell: (row) => (
        <div className="flex flex-col gap-0.5">
          <span className="tabular-nums">
            {formatCount(row.scope_count)}
            {row.privileged && <span className="ml-1.5 text-[11.5px] text-danger">privileged</span>}
          </span>
          <span className="text-[11.5px] text-fg-muted">{row.source_label}</span>
        </div>
      ),
    },
    { id: "instances", header: "Instances", cell: (row) => <InstanceChips instances={row.instances} /> },
    {
      id: "created_by",
      header: "Created by",
      cell: (row) => <span className="text-fg-secondary">{row.created_by.name}</span>,
    },
    {
      id: "last_used",
      header: "Last used",
      cell: (row) => (
        <span className="whitespace-nowrap text-fg-secondary">
          {row.last_used_at ? formatRelative(row.last_used_at) : "Never"}
        </span>
      ),
    },
    { id: "expires", header: "Expires", cell: (row) => <ExpiryCell row={row} /> },
  ];

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto px-6 pt-5 pb-10">
        <PageIntro
          title="Service accounts"
          actions={
            <PermissionGate scope="service_accounts:manage">
              <Button
                variant="primary"
                size="34"
                onClick={() => {
                  setCreating(true);
                }}
              >
                <Plus aria-hidden />
                New service account
              </Button>
            </PermissionGate>
          }
        >
          Machine callers such as CI, chat bridges and bots use opaque{" "}
          <code className="font-mono">agno_pat_</code> tokens. Runs are attributed to{" "}
          <code className="font-mono">sa:&lt;name&gt;</code>, and their scopes live in each instance&apos;s
          database.
        </PageIntro>

        {list.isError ? (
          <ErrorState {...describeError(list.error)} onRetry={() => void list.refetch()} />
        ) : list.isPending ? (
          <LoadingRows label="Loading service accounts" />
        ) : rows.length === 0 ? (
          <EmptyState title="No service accounts yet">
            Create one for each machine caller, so its runs are attributed to it and its scopes stay narrow.
          </EmptyState>
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <div className="min-w-[780px]">
              <DataTable
                label="Service accounts"
                columns={columns}
                rows={rows}
                rowKey={(row) => row.name}
                selectedKey={selected ?? ""}
                onRowClick={(row) => {
                  open(row.name);
                }}
                footer={
                  <>
                    <span className="mr-auto">
                      {formatCount(rows.length)} account{rows.length === 1 ? "" : "s"} ·{" "}
                      {formatCount(rows.reduce((sum, row) => sum + row.active_tokens, 0))} active tokens
                    </span>
                    <ApiHint call="GET /service-accounts" scope="org:read">
                      <code className="font-mono text-[11.5px]">GET /service-accounts</code>
                    </ApiHint>
                  </>
                }
              />
            </div>
          </div>
        )}

        <Callout tone="info">
          Service-account scopes are enforced on every REST route, in every auth mode. Scoped service accounts
          can&apos;t resolve approvals, even with <code className="font-mono">approvals:write</code>.
        </Callout>
      </div>
      {selected && (
        <AccountDetail
          key={selected}
          account={selected}
          onClose={() => {
            open(undefined);
          }}
          onDeleted={() => {
            open(undefined);
          }}
        />
      )}
      <CreateAccountSheet
        open={creating}
        onOpenChange={setCreating}
        onDone={(name) => {
          open(name);
        }}
      />
    </div>
  );
}
