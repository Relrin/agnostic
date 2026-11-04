// Connection › Network: how browsers reach the runtime (gateway or direct) and the client certificate (mTLS).
import {
  describeError,
  instancesGetInstanceQueryKey,
  instancesListInstancesQueryKey,
  instancesUpdateInstanceMutation,
  type InstanceOut,
} from "@agnostic/api";
import { PermissionGate } from "@agnostic/core";
import { Button, Callout, Field, Input, SegmentedControl, Textarea } from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

type NetworkMode = InstanceOut["network_mode"];

function Card({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5">
      <h2 className="text-[14.5px] font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function useUpdate(instance: InstanceOut) {
  const queryClient = useQueryClient();
  return useMutation({
    ...instancesUpdateInstanceMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: instancesGetInstanceQueryKey({ path: { instance: instance.slug } }),
      });
      await queryClient.invalidateQueries({ queryKey: instancesListInstancesQueryKey() });
    },
  });
}

export function NetworkCard({ instance }: { instance: InstanceOut }) {
  const update = useUpdate(instance);
  const [mode, setMode] = useState<NetworkMode>(instance.network_mode);
  const [browserUrl, setBrowserUrl] = useState(
    instance.browser_url === instance.endpoint_url ? "" : instance.browser_url,
  );
  const dirty =
    mode !== instance.network_mode || (browserUrl || instance.endpoint_url) !== instance.browser_url;

  return (
    <PermissionGate scope="os:write">
      <Card title="Network">
        <div className="grid max-w-2xl gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-fg-secondary">How browsers reach this runtime</span>
            <SegmentedControl<NetworkMode>
              label="Network mode"
              value={mode}
              onValueChange={setMode}
              options={[
                { value: "gateway", label: "Through the gateway" },
                { value: "direct", label: "Direct" },
              ]}
            />
          </div>
          {mode === "direct" ? (
            <>
              <Callout tone="warning" title="Direct mode trades gateway features for one less hop">
                Browsers fetch a short-lived token here and call the runtime themselves. AgentOS still
                enforces each person&apos;s scopes, but the gateway no longer explains denials, caches
                responses, applies its rate limits or elevates typed actions. The runtime needs TLS, CORS for
                this origin and its decision log on (audit=True) so calls still reach the audit log.
              </Callout>
              <Field
                label="Browser URL"
                hint={`Where browsers reach the runtime, when it isn't ${instance.endpoint_url}.`}
              >
                {({ id, describedBy }) => (
                  <Input
                    id={id}
                    mono
                    aria-describedby={describedBy}
                    placeholder="https://agentos.example.com"
                    value={browserUrl}
                    onChange={(event) => {
                      setBrowserUrl(event.target.value);
                    }}
                  />
                )}
              </Field>
            </>
          ) : (
            <p className="text-[13px] text-fg-secondary">
              Every call goes through the control plane: scopes are checked and explained, responses cached
              and each call audited. The runtime can stay on a private network.
            </p>
          )}
          {update.error && <Callout tone="danger">{describeError(update.error).reason}</Callout>}
          <div>
            <Button
              variant="primary"
              disabled={!dirty || update.isPending}
              onClick={() => {
                update.mutate({
                  path: { instance: instance.id },
                  body: { network_mode: mode, browser_url: browserUrl, version: instance.version },
                });
              }}
            >
              Save
            </Button>
          </div>
        </div>
      </Card>
    </PermissionGate>
  );
}

export function ClientCertificateCard({ instance }: { instance: InstanceOut }) {
  const update = useUpdate(instance);
  const [cert, setCert] = useState("");
  const [key, setKey] = useState("");

  return (
    <PermissionGate scope="os:write">
      <Card title="Client certificate">
        <p className="text-[13px] text-fg-secondary">
          {instance.has_client_certificate
            ? "The control plane presents a client certificate to this runtime (mutual TLS)."
            : "For runtimes behind a proxy that requires mutual TLS. The key is stored encrypted and never shown again."}
        </p>
        <div className="grid max-w-2xl gap-4">
          <Field label="Certificate chain (PEM)">
            {({ id }) => (
              <Textarea
                id={id}
                rows={4}
                placeholder="-----BEGIN CERTIFICATE-----"
                value={cert}
                onChange={(event) => {
                  setCert(event.target.value);
                }}
              />
            )}
          </Field>
          <Field label="Private key (PEM, unencrypted)">
            {({ id }) => (
              <Textarea
                id={id}
                rows={4}
                placeholder="-----BEGIN PRIVATE KEY-----"
                value={key}
                onChange={(event) => {
                  setKey(event.target.value);
                }}
              />
            )}
          </Field>
          {update.error && <Callout tone="danger">{describeError(update.error).reason}</Callout>}
          <div className="flex gap-2">
            <Button
              variant="primary"
              disabled={!cert.trim() || !key.trim() || update.isPending}
              onClick={() => {
                update.mutate(
                  {
                    path: { instance: instance.id },
                    body: { client_cert_pem: cert, client_key_pem: key, version: instance.version },
                  },
                  {
                    onSuccess: () => {
                      setCert("");
                      setKey("");
                    },
                  },
                );
              }}
            >
              {instance.has_client_certificate ? "Replace" : "Save"}
            </Button>
            {instance.has_client_certificate && (
              <Button
                variant="ghost"
                disabled={update.isPending}
                onClick={() => {
                  update.mutate({
                    path: { instance: instance.id },
                    body: { client_cert_pem: "", client_key_pem: "", version: instance.version },
                  });
                }}
              >
                Remove
              </Button>
            )}
          </div>
        </div>
      </Card>
    </PermissionGate>
  );
}
