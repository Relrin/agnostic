// Instance settings sections (03 §3: /i/:instance/settings/:section).
import {
  describeError,
  gatewayFetch,
  instancesDeleteInstanceMutation,
  instancesGetConfigQueryKey,
  instancesGetInstanceQueryKey,
  instancesGetKeysOptions,
  instancesGetKeysQueryKey,
  instancesListInstancesQueryKey,
  instancesRotateKeysMutation,
  instancesTestInstanceMutation,
  instancesUpdateInstanceMutation,
  instancesVerifyTokenMutation,
  type CapabilityOut,
  type ConfigOut,
  type InstanceOut,
} from "@agnostic/api";
import { PermissionGate, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  CodeBlock,
  EmptyState,
  EnvBadge,
  Field,
  Input,
  LoadingRows,
  SegmentedControl,
  StatusPill,
  StepList,
  Textarea,
  type Environment,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

function Card({ title, children, action }: { title: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-[14.5px] font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(140px,max-content)_1fr] gap-x-6 gap-y-2 text-[13px]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-fg-muted">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function useInvalidateInstance(instance: InstanceOut) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({
      queryKey: instancesGetInstanceQueryKey({ path: { instance: instance.slug } }),
    });
    await queryClient.invalidateQueries({ queryKey: instancesListInstancesQueryKey() });
  };
}

export function ConnectionSection({
  instance,
  capabilities,
}: {
  instance: InstanceOut;
  capabilities: readonly CapabilityOut[];
}) {
  const invalidate = useInvalidateInstance(instance);
  const test = useMutation({ ...instancesTestInstanceMutation(), onSuccess: invalidate });
  const update = useMutation({ ...instancesUpdateInstanceMutation(), onSuccess: invalidate });
  const [name, setName] = useState(instance.display_name);
  const [endpoint, setEndpoint] = useState(instance.endpoint_url);
  const [env, setEnv] = useState<Environment>(instance.env_tag);
  const dirty =
    name !== instance.display_name || endpoint !== instance.endpoint_url || env !== instance.env_tag;

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Connection"
        action={
          <PermissionGate scope="os:write">
            <Button
              size="30"
              variant="primary"
              disabled={test.isPending}
              onClick={() => {
                test.mutate({ path: { instance: instance.id } });
              }}
            >
              {test.isPending ? "Testing…" : "Test connection"}
            </Button>
          </PermissionGate>
        }
      >
        <Facts
          rows={[
            ["Status", <StatusPill key="s" status={instance.status.toUpperCase()} />],
            [
              "Endpoint",
              <span key="e" className="font-mono text-[12.5px]">
                {instance.endpoint_url}
              </span>,
            ],
            [
              "AgentOS id",
              <span key="o" className="font-mono text-[12.5px]">
                {instance.os_id ?? "—"}
              </span>,
            ],
            ["Version", instance.agno_version ? `agno ${instance.agno_version}` : "—"],
            ["Latency", instance.latency_ms === null ? "—" : `${String(instance.latency_ms)} ms`],
            ["Last seen", instance.last_seen_at ? new Date(instance.last_seen_at).toLocaleString() : "never"],
            [
              "TLS",
              instance.tls_verify
                ? instance.has_ca_bundle
                  ? "Verified (custom CA)"
                  : "Verified"
                : "Not verified",
            ],
          ]}
        />
        {instance.version_drift && (
          <Callout tone="warning" title={`${instance.version_drift} detected`}>
            Re-validate Studio contracts and the gateway's route policies against the new version.
          </Callout>
        )}
        {test.data && <StepList steps={test.data.steps} />}
        {test.error && <Callout tone="danger">{describeError(test.error).reason}</Callout>}
      </Card>

      <PermissionGate scope="os:write">
        <Card title="Details">
          <div className="grid max-w-2xl gap-4">
            <Field label="Name">
              {({ id }) => (
                <Input
                  id={id}
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                  }}
                />
              )}
            </Field>
            <Field label="Endpoint">
              {({ id }) => (
                <Input
                  id={id}
                  mono
                  value={endpoint}
                  onChange={(event) => {
                    setEndpoint(event.target.value);
                  }}
                />
              )}
            </Field>
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg-secondary">Environment</span>
              <SegmentedControl<Environment>
                label="Environment"
                value={env}
                onValueChange={setEnv}
                options={[
                  { value: "production", label: "Production" },
                  { value: "staging", label: "Staging" },
                  { value: "development", label: "Development" },
                ]}
              />
            </div>
            {update.error && <Callout tone="danger">{describeError(update.error).reason}</Callout>}
            <div>
              <Button
                variant="primary"
                disabled={!dirty || update.isPending}
                onClick={() => {
                  update.mutate({
                    path: { instance: instance.id },
                    body: {
                      display_name: name,
                      endpoint_url: endpoint,
                      env_tag: env,
                      version: instance.version,
                    },
                  });
                }}
              >
                Save
              </Button>
            </div>
          </div>
        </Card>
      </PermissionGate>

      <Card title="Capabilities">
        {capabilities.length === 0 ? (
          <p className="text-[13px] text-fg-secondary">
            Run Test connection to detect what this runtime supports.
          </p>
        ) : (
          <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {capabilities.map((capability) => (
              <li key={capability.name} className="flex items-center justify-between gap-3 text-[13px]">
                <span title={capability.detail || undefined}>{capability.label}</span>
                <Badge
                  tone={
                    capability.status === "available"
                      ? "success"
                      : capability.status === "disabled"
                        ? "muted"
                        : "outline"
                  }
                >
                  {capability.status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

const MODE_TEXT: Record<InstanceOut["auth_mode"], { title: string; body: string }> = {
  jwt: {
    title: "JWT authorization",
    body: "Every call carries a short-lived token with the person's scopes.",
  },
  security_key: {
    title: "Security key",
    body: "One shared key: no per-user permissions. Only Instance admins can use this runtime.",
  },
  none: { title: "No authentication", body: "Development only. Only Owners and Administrators can use it." },
  unknown: { title: "Unknown", body: "Run Test connection to read the mode from /info." },
};

export function AuthorizationSection({ instance }: { instance: InstanceOut }) {
  const queryClient = useQueryClient();
  const keys = useQuery(withQueryFn(instancesGetKeysOptions({ path: { instance: instance.id } })));
  const rotate = useMutation({
    ...instancesRotateKeysMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(instancesGetKeysQueryKey({ path: { instance: instance.id } }), data);
    },
  });
  const verify = useMutation(instancesVerifyTokenMutation());
  const [token, setToken] = useState("");
  const mode = MODE_TEXT[instance.auth_mode];
  const staged = keys.data?.keys.some((key) => key.status === "next") ?? false;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Mode">
          <p className="text-[13.5px] font-medium">{mode.title}</p>
          <p className="text-[13px] text-fg-secondary">{mode.body}</p>
        </Card>
        <Card title="User isolation">
          <p className="text-[13px] text-fg-secondary">
            {instance.user_isolation
              ? "On: people see only their own sessions and memories, unless they're Instance admins."
              : "Off: anyone with sessions:read sees every session."}
          </p>
        </Card>
      </div>

      <Card
        title="JWT verification"
        action={
          <PermissionGate scope="os:keys:rotate">
            <div className="flex gap-2">
              {staged ? (
                <>
                  <Button
                    size="30"
                    variant="outline"
                    onClick={() => {
                      rotate.mutate({ path: { instance: instance.id }, body: { action: "cancel" } });
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="30"
                    variant="primary"
                    onClick={() => {
                      rotate.mutate({ path: { instance: instance.id }, body: { action: "activate" } });
                    }}
                  >
                    Activate next key
                  </Button>
                </>
              ) : (
                <Button
                  size="30"
                  onClick={() => {
                    rotate.mutate({ path: { instance: instance.id }, body: { action: "stage" } });
                  }}
                >
                  Rotate key pair
                </Button>
              )}
            </div>
          </PermissionGate>
        }
      >
        {keys.isPending ? (
          <LoadingRows rows={2} label="Loading keys" />
        ) : keys.isError ? (
          <Callout tone="danger">{describeError(keys.error).reason}</Callout>
        ) : (
          <>
            <Facts
              rows={[
                ["Token source", "Authorization header (Bearer)"],
                [
                  "Issuer",
                  <span key="i" className="font-mono text-[12.5px]">
                    {keys.data.issuer}
                  </span>,
                ],
                [
                  "Audience",
                  <span key="a" className="font-mono text-[12.5px]">
                    {keys.data.audience}
                  </span>,
                ],
                [
                  "JWKS",
                  <a
                    key="j"
                    className="font-mono text-[12.5px] text-info hover:underline"
                    href={keys.data.jwks_path}
                  >
                    {keys.data.jwks_path}
                  </a>,
                ],
              ]}
            />
            <p className="text-[12.5px] text-fg-secondary">{keys.data.rotation_note}</p>
            {keys.data.keys.map((key) => (
              <div key={key.kid} className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-[13px]">
                  <Badge tone={key.status === "active" ? "success" : "warning"}>{key.status}</Badge>
                  <span className="font-mono text-[12px] text-fg-secondary">fingerprint {key.kid}</span>
                  <a
                    className="ml-auto text-[12.5px] text-info hover:underline"
                    download={`${instance.slug}-${key.status}.pem`}
                    href={`data:application/x-pem-file;charset=utf-8,${encodeURIComponent(key.public_pem)}`}
                  >
                    Download public key
                  </a>
                </div>
              </div>
            ))}
            {keys.data.env_snippet && <CodeBlock title="Runtime environment" code={keys.data.env_snippet} />}
            {keys.data.python_snippet && <CodeBlock title="app.py" code={keys.data.python_snippet} />}
          </>
        )}
        {rotate.error && <Callout tone="danger">{describeError(rotate.error).reason}</Callout>}
      </Card>

      <Card title="Verify a token">
        <Field
          label="JWT"
          hint="Paste a token to check its signature, audience and expiry against this instance's keys."
        >
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              value={token}
              onChange={(event) => {
                setToken(event.target.value);
              }}
            />
          )}
        </Field>
        <div>
          <Button
            size="30"
            disabled={token.length < 10 || verify.isPending}
            onClick={() => {
              verify.mutate({ path: { instance: instance.id }, body: { token: token.trim() } });
            }}
          >
            Verify
          </Button>
        </div>
        {verify.data && (
          <Callout
            tone={verify.data.valid ? "insight" : "danger"}
            title={verify.data.valid ? "Valid" : "Not valid"}
          >
            {verify.data.error ??
              `Signed with ${verify.data.key_status ?? "an unknown"} key ${verify.data.kid ?? ""}`}
            {verify.data.claims && (
              <CodeBlock title="Claims" code={JSON.stringify(verify.data.claims, null, 2)} />
            )}
          </Callout>
        )}
      </Card>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function dbId(entry: unknown): string {
  if (typeof entry === "string") return entry;
  const record = asRecord(entry);
  const value = record?.id ?? record?.db_id;
  return typeof value === "string" ? value : JSON.stringify(entry);
}

export function DatabasesSection({ instance, config }: { instance: InstanceOut; config: ConfigOut }) {
  const queryClient = useQueryClient();
  const migrate = useMutation({
    mutationFn: async (target: string) => {
      const response = await gatewayFetch(instance.slug, `databases/${encodeURIComponent(target)}/migrate`, {
        method: "POST",
      });
      return (await response.json()) as unknown;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: instancesGetConfigQueryKey({ path: { instance: instance.slug } }),
      });
    },
  });
  const databases = config.databases.map(dbId);
  if (databases.length === 0)
    return <EmptyState title="No databases">This runtime reports no databases.</EmptyState>;
  return (
    <Card
      title="Databases"
      action={
        <PermissionGate scope="config:write" instance={instance.slug}>
          <Button
            size="30"
            disabled={migrate.isPending}
            onClick={() => {
              migrate.mutate("all");
            }}
          >
            Migrate all
          </Button>
        </PermissionGate>
      }
    >
      <ul className="flex flex-col divide-y divide-divider-row">
        {databases.map((id) => (
          <li key={id} className="flex items-center gap-3 py-2.5 text-[13px]">
            <span className="font-mono">{id}</span>
            {String(config.os_database) === id && <Badge tone="info">OS database</Badge>}
            <PermissionGate scope="config:write" instance={instance.slug}>
              <Button
                className="ml-auto"
                size="28"
                variant="outline"
                disabled={migrate.isPending}
                onClick={() => {
                  migrate.mutate(id);
                }}
              >
                Migrate
              </Button>
            </PermissionGate>
          </li>
        ))}
      </ul>
      {migrate.isSuccess && <Callout tone="insight">Migration finished.</Callout>}
      {migrate.error && <Callout tone="danger">{describeError(migrate.error).reason}</Callout>}
    </Card>
  );
}

export function InterfacesSection({ config }: { config: ConfigOut }) {
  if (config.interfaces.length === 0) {
    return (
      <EmptyState title="No interfaces">
        This runtime exposes no Slack, WhatsApp, AG-UI or A2A interfaces.
      </EmptyState>
    );
  }
  return (
    <Card title="Interfaces">
      <ul className="flex flex-col divide-y divide-divider-row">
        {config.interfaces.map((entry, index) => {
          const record = asRecord(entry) ?? {};
          const type = typeof record.type === "string" ? record.type : `interface ${String(index + 1)}`;
          const route = typeof record.route === "string" ? record.route : "";
          return (
            <li key={`${type}-${route}`} className="flex items-center gap-3 py-2.5 text-[13px]">
              <span className="font-medium">{type}</span>
              <span className="font-mono text-fg-secondary">{route}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function SectionJson({ title, value, empty }: { title: string; value: unknown; empty: string }) {
  if (value === undefined || value === null)
    return <EmptyState title={`No ${title.toLowerCase()} section`}>{empty}</EmptyState>;
  return (
    <Card title={title}>
      <CodeBlock title={`/config · ${title.toLowerCase()}`} code={JSON.stringify(value, null, 2)} />
    </Card>
  );
}

export function DangerZone({ instance, onDeleted }: { instance: InstanceOut; onDeleted: () => void }) {
  const invalidate = useInvalidateInstance(instance);
  const update = useMutation({ ...instancesUpdateInstanceMutation(), onSuccess: invalidate });
  const remove = useMutation({ ...instancesDeleteInstanceMutation(), onSuccess: onDeleted });
  const [confirm, setConfirm] = useState("");
  const disabled = instance.status === "disabled";
  return (
    <div className="flex flex-col gap-4">
      <PermissionGate
        scope="os:write"
        fallback={
          <Callout tone="availability">Only Owners and Administrators can change this instance.</Callout>
        }
      >
        <Card title={disabled ? "Enable the instance" : "Disable the instance"}>
          <p className="text-[13px] text-fg-secondary">
            {disabled
              ? "The gateway accepts calls to it again."
              : "The gateway stops calling it and health checks pause. The runtime keeps running."}
          </p>
          <div>
            <Button
              variant="destructive-outline"
              disabled={update.isPending}
              onClick={() => {
                update.mutate({
                  path: { instance: instance.id },
                  body: { status: disabled ? "enabled" : "disabled" },
                });
              }}
            >
              {disabled ? "Enable" : "Disable"}
            </Button>
          </div>
        </Card>
      </PermissionGate>
      <PermissionGate scope="os:delete">
        <Card title="Delete the instance record">
          <p className="text-[13px] text-fg-secondary">
            Removes {instance.display_name} from Agnostic with its keys and snapshots. The runtime keeps
            running and still trusts the old public key until you remove it there. This can't be undone.
          </p>
          <Field label={`Type ${instance.slug} to confirm`}>
            {({ id }) => (
              <Input
                id={id}
                mono
                value={confirm}
                onChange={(event) => {
                  setConfirm(event.target.value);
                }}
              />
            )}
          </Field>
          {remove.error && <Callout tone="danger">{describeError(remove.error).reason}</Callout>}
          <div>
            <Button
              variant="destructive-outline"
              disabled={confirm !== instance.slug || remove.isPending}
              onClick={() => {
                remove.mutate({ path: { instance: instance.id }, query: { confirm } });
              }}
            >
              Delete instance record
            </Button>
          </div>
        </Card>
      </PermissionGate>
      <p className="text-[12.5px] text-fg-muted">
        Environment: <EnvBadge env={instance.env_tag} />
      </p>
    </div>
  );
}
