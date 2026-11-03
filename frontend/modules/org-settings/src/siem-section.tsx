// SIEM streaming: every audit event is delivered (at least once) to HTTPS webhooks, syslog or OTLP log endpoints,
// as JSON, OCSF or CEF.
import {
  auditCreateSinkMutation,
  auditDeleteSinkMutation,
  auditListSinksOptions,
  auditListSinksQueryKey,
  auditStreamStatusOptions,
  auditTestSinkMutation,
  auditUpdateSinkMutation,
  describeError,
  type SinkFormatName,
  type SinkIn,
  type SinkKindName,
  type SinkOut,
  type SinkTestOut,
} from "@agnostic/api";
import { formatRelative, useReauth, withQueryFn, withReauth } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  SegmentedControl,
  StatusPill,
  Switch,
  Textarea,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { Section, useWritable } from "./shared";

const KIND_LABELS: Record<SinkKindName, string> = {
  https_webhook: "HTTPS webhook",
  syslog: "Syslog",
  otlp_logs: "OTLP logs",
};

const FORMAT_LABELS: Record<SinkFormatName, string> = { json: "JSON", ocsf: "OCSF", cef: "CEF" };

const STATUS_TONES = { ok: "success", failing: "danger", paused: "warning" } as const;

type SinkForm = {
  name: string;
  kind: SinkKindName;
  format: SinkFormatName;
  enabled: boolean;
  url: string;
  secret: string;
  headers: string;
  host: string;
  port: string;
  tls: boolean;
  tlsVerify: boolean;
  caPem: string;
  hostname: string;
  endpoint: string;
};

const str = (value: unknown) =>
  typeof value === "string" ? value : typeof value === "number" ? String(value) : "";

function sinkForm(sink: SinkOut | undefined): SinkForm {
  const config = sink?.config ?? {};
  return {
    name: sink?.name ?? "",
    kind: sink?.kind ?? "https_webhook",
    format: sink?.format ?? "json",
    enabled: sink?.enabled ?? true,
    url: str(config.url),
    secret: "",
    headers: "",
    host: str(config.host),
    port: str(config.port) || "6514",
    tls: config.tls !== false,
    tlsVerify: config.tls_verify !== false,
    caPem: str(config.ca_pem),
    hostname: str(config.hostname),
    endpoint: str(config.endpoint),
  };
}

/** "Name: value" lines → headers. */
function parseHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const index = line.indexOf(":");
    if (index <= 0) continue;
    headers[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return headers;
}

/** The kind's config; secrets (webhook secret, header values) only when typed, so saved ones are kept. */
export function sinkConfig(form: SinkForm): Record<string, unknown> {
  const headers = form.headers.trim() ? { headers: parseHeaders(form.headers) } : {};
  if (form.kind === "https_webhook")
    return { url: form.url.trim(), ...(form.secret ? { secret: form.secret } : {}), ...headers };
  if (form.kind === "otlp_logs") return { endpoint: form.endpoint.trim(), ...headers };
  return {
    host: form.host.trim(),
    port: Number(form.port),
    tls: form.tls,
    tls_verify: form.tlsVerify,
    ...(form.caPem.trim() ? { ca_pem: form.caPem.trim() } : {}),
    ...(form.hostname.trim() ? { hostname: form.hostname.trim() } : {}),
  };
}

function TestResult({ result }: { result: SinkTestOut }) {
  return (
    <Callout
      tone={result.ok ? "insight" : "danger"}
      title={result.ok ? "Test event delivered" : "Delivery failed"}
    >
      {[
        result.status_code !== null ? `HTTP ${String(result.status_code)}` : null,
        result.latency_ms !== null ? `${String(result.latency_ms)} ms` : null,
        result.error,
      ]
        .filter(Boolean)
        .join(" · ") || (result.ok ? "Accepted." : "No answer.")}
    </Callout>
  );
}

function SinkDialog({ sink, onClose }: { sink: SinkOut | undefined; onClose: () => void }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const [form, setForm] = useState(() => sinkForm(sink));
  const set =
    <K extends keyof SinkForm>(key: K) =>
    (value: SinkForm[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
    };
  const done = async (message: string) => {
    await queryClient.invalidateQueries({ queryKey: auditListSinksQueryKey() });
    toast(message);
    onClose();
  };
  const create = useMutation({
    ...withReauth(reauth, auditCreateSinkMutation()),
    onSuccess: (data) => done(`${data.name} is streaming`),
  });
  const update = useMutation({
    ...withReauth(reauth, auditUpdateSinkMutation()),
    onSuccess: (data) => done(`${data.name} saved`),
  });
  const error = create.error ?? update.error;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const config = sinkConfig(form);
    if (sink) {
      update.mutate({
        path: { sink_id: sink.id },
        body: { name: form.name.trim(), format: form.format, enabled: form.enabled, config },
      });
    } else {
      const body: SinkIn = {
        name: form.name.trim(),
        kind: form.kind,
        format: form.format,
        enabled: form.enabled,
        config,
      };
      create.mutate({ body });
    }
  };

  const input = (
    label: string,
    key: "url" | "secret" | "host" | "port" | "hostname" | "endpoint",
    options: { hint?: string; placeholder?: string; type?: string; required?: boolean } = {},
  ) => (
    <Field label={label} hint={options.hint}>
      {({ id, describedBy }) => (
        <Input
          id={id}
          mono
          type={options.type ?? "text"}
          required={options.required}
          placeholder={options.placeholder}
          aria-describedby={describedBy}
          value={form[key]}
          onChange={(event) => {
            set(key)(event.target.value);
          }}
        />
      )}
    </Field>
  );
  const headerNames = Array.isArray(sink?.config.header_names) ? (sink.config.header_names as string[]) : [];
  const headersField = (
    <Field
      label="Headers"
      hint={
        headerNames.length > 0
          ? `Saved: ${headerNames.join(", ")}. Values are write-only; enter all headers again to replace them.`
          : "One per line: Name: value (e.g. Authorization: Splunk …). Values are write-only."
      }
    >
      {({ id, describedBy }) => (
        <Textarea
          id={id}
          className="min-h-16"
          aria-describedby={describedBy}
          value={form.headers}
          onChange={(event) => {
            set("headers")(event.target.value);
          }}
        />
      )}
    </Field>
  );

  return (
    <form className="flex flex-col gap-4" onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>{sink ? `Edit ${sink.name}` : "Add a SIEM destination"}</DialogTitle>
        <DialogDescription>
          Every audit event is delivered at least once, in order per destination.
        </DialogDescription>
      </DialogHeader>
      <Field label="Name">
        {({ id }) => (
          <Input
            id={id}
            required
            placeholder="Splunk HEC"
            value={form.name}
            onChange={(event) => {
              set("name")(event.target.value);
            }}
          />
        )}
      </Field>
      {!sink && (
        <SegmentedControl
          label="Destination type"
          value={form.kind}
          options={(Object.keys(KIND_LABELS) as SinkKindName[]).map((value) => ({
            value,
            label: KIND_LABELS[value],
          }))}
          onValueChange={(value) => {
            setForm({ ...form, kind: value, format: value === "syslog" ? "cef" : form.format });
          }}
        />
      )}
      <SegmentedControl
        label="Format"
        value={form.format}
        options={(Object.keys(FORMAT_LABELS) as SinkFormatName[]).map((value) => ({
          value,
          label: FORMAT_LABELS[value],
        }))}
        onValueChange={set("format")}
      />
      {form.kind === "https_webhook" && (
        <>
          {input("URL", "url", { required: true, placeholder: "https://siem.example.com/ingest" })}
          {input("Signing secret", "secret", {
            type: "password",
            hint: sink?.has_secret
              ? "Saved. Leave empty to keep it."
              : "Optional. Each request then carries X-Agnostic-Signature: t=<unix>,v1=<hex HMAC-SHA256 of “<unix>.<body>”>; verify it and reject old timestamps.",
          })}
          {headersField}
        </>
      )}
      {form.kind === "syslog" && (
        <>
          <div className="grid grid-cols-[1fr_120px] gap-3">
            {input("Host", "host", { required: true, placeholder: "siem.internal" })}
            {input("Port", "port", { required: true, type: "number" })}
          </div>
          <Switch
            label="TLS"
            description="RFC 5425 syslog over TLS (recommended)."
            checked={form.tls}
            onCheckedChange={set("tls")}
          />
          {form.tls && (
            <>
              <Switch
                label="Verify the certificate"
                checked={form.tlsVerify}
                onCheckedChange={set("tlsVerify")}
              />
              <Field label="CA certificate (PEM)" hint="Only for a private CA.">
                {({ id, describedBy }) => (
                  <Textarea
                    id={id}
                    className="min-h-16"
                    aria-describedby={describedBy}
                    value={form.caPem}
                    onChange={(event) => {
                      set("caPem")(event.target.value);
                    }}
                  />
                )}
              </Field>
            </>
          )}
          {input("Hostname", "hostname", { hint: "Sent in the syslog header. Empty uses the server's." })}
        </>
      )}
      {form.kind === "otlp_logs" && (
        <>
          {input("Endpoint", "endpoint", { required: true, placeholder: "https://otel.example.com/v1/logs" })}
          {headersField}
        </>
      )}
      <Switch label="Enabled" checked={form.enabled} onCheckedChange={set("enabled")} />
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={create.isPending || update.isPending}>
          {sink ? "Save destination" : "Add destination"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function SiemSection() {
  const { writable, note } = useWritable("settings:write");
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const sinks = useQuery(withQueryFn(auditListSinksOptions()));
  const stream = useQuery({ ...withQueryFn(auditStreamStatusOptions()), refetchInterval: 15_000 });
  const [dialog, setDialog] = useState<{ sink: SinkOut | undefined } | null>(null);
  const [tested, setTested] = useState<{ id: string; result: SinkTestOut } | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: auditListSinksQueryKey() });
  const toggle = useMutation({ ...withReauth(reauth, auditUpdateSinkMutation()), onSuccess: refresh });
  const remove = useMutation({
    ...withReauth(reauth, auditDeleteSinkMutation()),
    onSuccess: async () => {
      toast("Destination removed");
      await refresh();
    },
  });
  const test = useMutation({
    ...withReauth(reauth, auditTestSinkMutation()),
    onSuccess: async (result, variables) => {
      setTested({ id: variables.path.sink_id, result });
      await refresh();
    },
  });

  const columns: Column<SinkOut>[] = [
    {
      id: "name",
      header: "Destination",
      cell: (row) => (
        <div className="flex flex-col">
          <span className="font-medium">{row.name}</span>
          <span className="font-mono text-[12px] text-fg-muted">
            {str(row.config.url) ||
              str(row.config.endpoint) ||
              `${str(row.config.host)}:${str(row.config.port)}`}
          </span>
        </div>
      ),
    },
    {
      id: "kind",
      header: "Type",
      cell: (row) => (
        <span className="flex items-center gap-1.5">
          {KIND_LABELS[row.kind]}
          <Badge tone="outline">{FORMAT_LABELS[row.format]}</Badge>
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <div className="flex flex-col gap-0.5">
          <span>
            <StatusPill status={row.status} tone={STATUS_TONES[row.status]} />
          </span>
          <span className="text-[12px] text-fg-muted">
            {row.last_event_at ? `last event ${formatRelative(row.last_event_at)}` : "no events yet"}
          </span>
          {row.last_error && (
            <span className="text-[12px] text-danger">
              {row.last_error}
              {row.failure_count > 0 ? ` · ${String(row.failure_count)} failures` : ""}
            </span>
          )}
        </div>
      ),
    },
    {
      id: "enabled",
      header: "Enabled",
      cell: (row) => (
        <Switch
          hideLabel
          label={`Enable ${row.name}`}
          checked={row.enabled}
          disabled={!writable || toggle.isPending}
          onCheckedChange={(checked) => {
            toggle.mutate({ path: { sink_id: row.id }, body: { enabled: checked } });
          }}
        />
      ),
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        writable ? (
          <span className="inline-flex gap-1">
            <Button
              size="28"
              variant="ghost"
              aria-label={`Send a test event to ${row.name}`}
              disabled={test.isPending}
              onClick={() => {
                setTested(null);
                test.mutate({ path: { sink_id: row.id } });
              }}
            >
              Test
            </Button>
            <Button
              size="28"
              variant="ghost"
              onClick={() => {
                setDialog({ sink: row });
              }}
            >
              Edit
            </Button>
            <Button
              size="28"
              variant="destructive-text"
              aria-label={`Remove ${row.name}`}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Stop streaming to ${row.name} and remove it?`))
                  remove.mutate({ path: { sink_id: row.id } });
              }}
            >
              Remove
            </Button>
          </span>
        ) : null,
    },
  ];

  const testedSink = sinks.data?.find((sink) => sink.id === tested?.id);
  const error = toggle.error ?? remove.error ?? test.error;
  return (
    <div className="flex flex-col gap-5">
      {note}
      <Section
        title="SIEM streaming"
        description="Stream the audit log to Splunk, Elastic, Datadog, Sentinel or any collector. Delivery is at least once and survives restarts."
        action={
          <span className="flex items-center gap-2">
            {stream.data && (
              <Badge tone={stream.data.streaming ? "success" : "muted"}>
                {stream.data.streaming
                  ? `Streaming · last event ${formatRelative(stream.data.last_event_at)}`
                  : "Not streaming"}
              </Badge>
            )}
            {writable && (
              <Button
                size="30"
                variant="primary"
                onClick={() => {
                  setDialog({ sink: undefined });
                }}
              >
                Add destination
              </Button>
            )}
          </span>
        }
      >
        {sinks.isPending ? (
          <LoadingRows rows={2} label="Loading destinations" />
        ) : sinks.isError ? (
          <ErrorState reason={describeError(sinks.error).reason} onRetry={() => void sinks.refetch()} />
        ) : (
          <DataTable
            label="SIEM destinations"
            columns={columns}
            rows={sinks.data}
            rowKey={(row) => row.id}
            empty={
              <p className="text-[13px] text-fg-muted">No destinations: events stay in the audit log only.</p>
            }
          />
        )}
        {tested && (
          <div className="flex flex-col gap-1">
            <span className="text-[12.5px] text-fg-muted">
              Test delivery to {testedSink?.name ?? "destination"}
            </span>
            <TestResult result={tested.result} />
          </div>
        )}
        {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
      </Section>
      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] max-w-xl overflow-y-auto">
          {dialog && (
            <SinkDialog
              sink={dialog.sink}
              onClose={() => {
                setDialog(null);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
