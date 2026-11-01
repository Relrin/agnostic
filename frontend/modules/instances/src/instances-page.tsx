import { describeError, type InstanceOut } from "@agnostic/api";
import { PermissionGate, useInstances } from "@agnostic/core";
import { Button, EmptyState, EnvBadge, ErrorState, LoadingRows, PageIntro, StatusPill } from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";

const STATUS: Record<InstanceOut["status"], string> = {
  connected: "ACTIVE",
  pending: "PENDING",
  unreachable: "FAILED",
  disabled: "DISABLED",
};

function lastSeen(value: string | null): string {
  if (!value) return "never";
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${String(Math.round(seconds / 60))} min ago`;
  return new Date(value).toLocaleString();
}

/** `/instances`: every connected AgentOS, and the way to connect one. */
export function InstancesPage() {
  const instances = useInstances();
  const connect = (
    <PermissionGate scope="os:write">
      <Button asChild variant="primary">
        <Link to="/instances/connect">
          <Plus aria-hidden />
          Connect instance
        </Link>
      </Button>
    </PermissionGate>
  );
  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Instances" actions={instances.data?.length ? connect : undefined}>
        The AgentOS runtimes this control plane manages. Everyone reaches them through the gateway, with their
        own permissions.
      </PageIntro>
      {instances.isPending ? (
        <LoadingRows rows={3} label="Loading instances" />
      ) : instances.isError ? (
        <ErrorState reason={describeError(instances.error).reason} onRetry={() => void instances.refetch()} />
      ) : instances.data.length === 0 ? (
        <EmptyState title="Connect your first instance" action={connect}>
          Point the control plane at an AgentOS (agno 3.1 or later). It discovers the runtime, generates a key
          pair and shows the snippet to paste into the runtime.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <thead className="border-b border-border-subtle text-[11.5px] tracking-[0.06em] text-fg-muted uppercase">
              <tr>
                <th className="px-4 py-2.5 font-medium">Instance</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Version</th>
                <th className="px-4 py-2.5 font-medium">Auth</th>
                <th className="px-4 py-2.5 font-medium">Latency</th>
                <th className="px-4 py-2.5 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider-row">
              {instances.data.map((instance) => (
                <tr key={instance.id} className="bg-surface">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Link
                        to="/i/$instance/settings"
                        params={{ instance: instance.slug }}
                        className="font-medium hover:underline"
                      >
                        {instance.display_name}
                      </Link>
                      <EnvBadge env={instance.env_tag} />
                    </div>
                    <div className="font-mono text-[11.5px] text-fg-muted">{instance.endpoint_url}</div>
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={STATUS[instance.status]} />
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px]">
                    {instance.agno_version ? `agno ${instance.agno_version}` : "—"}
                    {instance.version_drift && (
                      <div className="text-[11.5px] text-warning">{instance.version_drift}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px]">{instance.auth_mode}</td>
                  <td className="px-4 py-3">
                    {instance.latency_ms === null ? "—" : `${String(instance.latency_ms)} ms`}
                  </td>
                  <td className="px-4 py-3 text-fg-secondary">{lastSeen(instance.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
