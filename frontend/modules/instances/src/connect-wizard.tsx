import {
  describeError,
  instancesConnectInstanceMutation,
  instancesGetKeysOptions,
  instancesListInstancesQueryKey,
  instancesProbeEndpointMutation,
  instancesTestInstanceMutation,
  type InstanceOut,
  type ProbeOut,
  type ProblemDetails,
  type StepOut,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import {
  Button,
  Callout,
  CodeBlock,
  Field,
  Input,
  LoadingRows,
  PageIntro,
  SegmentedControl,
  StepList,
  Switch,
  Textarea,
  type Environment,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

type Stage = "endpoint" | "details" | "trust" | "done";

const STAGES: { id: Stage; label: string }[] = [
  { id: "endpoint", label: "Endpoint" },
  { id: "details", label: "Discovery" },
  { id: "trust", label: "Key & test" },
  { id: "done", label: "Done" },
];

function Progress({ stage }: { stage: Stage }) {
  const current = STAGES.findIndex((item) => item.id === stage);
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Connect steps">
      {STAGES.map((item, index) => (
        <li
          key={item.id}
          aria-current={index === current ? "step" : undefined}
          className={
            index === current
              ? "rounded-full bg-accent/12 px-3 py-1 text-[12.5px] font-medium text-accent"
              : "rounded-full bg-surface-hover px-3 py-1 text-[12.5px] text-fg-muted"
          }
        >
          {index + 1}. {item.label}
        </li>
      ))}
    </ol>
  );
}

function steps(items: readonly StepOut[]) {
  return <StepList steps={items} />;
}

function TrustStep({
  instance,
  onConnected,
}: {
  instance: InstanceOut;
  onConnected: (report: InstanceOut) => void;
}) {
  const keys = useQuery(withQueryFn(instancesGetKeysOptions({ path: { instance: instance.id } })));
  const queryClient = useQueryClient();
  const test = useMutation({
    ...instancesTestInstanceMutation(),
    onSuccess: async (report) => {
      await queryClient.invalidateQueries({ queryKey: instancesListInstancesQueryKey() });
      if (report.ok) onConnected(report.instance);
    },
  });
  if (keys.isPending) return <LoadingRows rows={3} label="Loading the key pair" />;
  if (keys.isError) return <Callout tone="danger">{describeError(keys.error).reason}</Callout>;
  const active = keys.data.keys.find((key) => key.status === "active");
  return (
    <div className="flex flex-col gap-4">
      {instance.auth_mode === "jwt" || instance.auth_mode === "unknown" ? (
        <>
          <p className="text-[13.5px] text-fg-secondary">
            The control plane generated an RS256 key pair for {instance.display_name}. Give the runtime the
            public key and turn on authorization, then restart it.
          </p>
          {keys.data.env_snippet && (
            <CodeBlock title="Environment (.env of the runtime)" code={keys.data.env_snippet} />
          )}
          {keys.data.python_snippet && <CodeBlock title="app.py" code={keys.data.python_snippet} />}
          {active && (
            <CodeBlock title={`Public key · kid ${active.kid.slice(0, 12)}…`} code={active.public_pem} />
          )}
        </>
      ) : (
        <Callout tone="warning" title={`This runtime uses ${instance.auth_mode}`}>
          {instance.auth_mode === "none"
            ? "No authentication: only development instances may run like this, and only Owners and Administrators can use it. Turn on JWT authorization with the snippet in Settings › Authorization."
            : "Security-key runtimes have no per-user permissions: only Instance admins can use them through the gateway."}
        </Callout>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          disabled={test.isPending}
          onClick={() => {
            test.mutate({ path: { instance: instance.id } });
          }}
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </Button>
        <span className="text-[12.5px] text-fg-muted">
          DNS, TLS, version, the token, and enforced scopes.
        </span>
      </div>
      {test.data && steps(test.data.steps)}
      {test.data && !test.data.ok && (
        <Callout tone="availability">
          Fix the failing step and test again. You can also finish later from Settings › Connection.
        </Callout>
      )}
      {test.error && <Callout tone="danger">{describeError(test.error).reason}</Callout>}
    </div>
  );
}

/** `/instances/connect`: endpoint → discovery result → key + snippet → test → done, with step-wise diagnostics. */
export function ConnectWizard() {
  const [stage, setStage] = useState<Stage>("endpoint");
  const [endpoint, setEndpoint] = useState("");
  const [tlsVerify, setTlsVerify] = useState(true);
  const [caBundle, setCaBundle] = useState("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [env, setEnv] = useState<Environment>("development");
  const [securityKey, setSecurityKey] = useState("");
  const [probe, setProbe] = useState<ProbeOut | undefined>(undefined);
  const [instance, setInstance] = useState<InstanceOut | undefined>(undefined);

  const probeMutation = useMutation({
    ...instancesProbeEndpointMutation(),
    onSuccess: (result) => {
      setProbe(result);
      if (result.ok && result.discovery) {
        setName(result.discovery.name ?? result.discovery.os_id);
        setStage("details");
      }
    },
  });
  const connect = useMutation({
    ...instancesConnectInstanceMutation(),
    onSuccess: (result) => {
      setInstance(result.instance);
      setStage("trust");
    },
  });

  const submitEndpoint = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    probeMutation.mutate({
      body: { endpoint_url: endpoint, tls_verify: tlsVerify, ca_bundle_pem: caBundle || null },
    });
  };
  const submitDetails = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    connect.mutate({
      body: {
        endpoint_url: endpoint,
        tls_verify: tlsVerify,
        ca_bundle_pem: caBundle || null,
        display_name: name,
        slug: slug || null,
        env_tag: env,
        security_key: securityKey || null,
        sub_claim_mode: "user_id",
      },
    });
  };
  const connectProblem: ProblemDetails | null = connect.error;

  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Connect an instance">
        Agnostic talks to AgentOS over its REST API and signs every call with a per-instance key, so each
        person gets their own permissions on the runtime.
      </PageIntro>
      <Progress stage={stage} />

      {stage === "endpoint" && (
        <form onSubmit={submitEndpoint} className="flex flex-col gap-4">
          <Field
            label="AgentOS endpoint"
            hint="The base URL, reachable from the control plane: e.g. http://agentos:7777"
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                mono
                required
                placeholder="https://agentos.internal:7777"
                aria-describedby={describedBy}
                value={endpoint}
                onChange={(event) => {
                  setEndpoint(event.target.value);
                }}
              />
            )}
          </Field>
          <Switch
            label="Verify TLS certificates"
            description="Turn off only for development runtimes with self-signed certificates."
            checked={tlsVerify}
            onCheckedChange={setTlsVerify}
          />
          <Field label="CA bundle (optional)" hint="PEM of the CA that signed the runtime's certificate.">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                value={caBundle}
                onChange={(event) => {
                  setCaBundle(event.target.value);
                }}
              />
            )}
          </Field>
          <div>
            <Button type="submit" variant="primary" disabled={probeMutation.isPending || !endpoint}>
              {probeMutation.isPending ? "Discovering…" : "Discover"}
            </Button>
          </div>
          {probe && !probe.ok && steps(probe.steps)}
          {probeMutation.error && (
            <Callout tone="danger">{describeError(probeMutation.error).reason}</Callout>
          )}
        </form>
      )}

      {stage === "details" && probe?.discovery && (
        <form onSubmit={submitDetails} className="flex flex-col gap-4">
          {steps(probe.steps)}
          <Callout
            tone="insight"
            title={`${probe.discovery.name ?? probe.discovery.os_id} · agno ${probe.discovery.agno_version}`}
          >
            {probe.discovery.agent_count} agents, {probe.discovery.team_count} teams,{" "}
            {probe.discovery.workflow_count} workflows · authentication: {probe.discovery.auth_mode}
            {probe.discovery.user_isolation ? " · user isolation on" : ""}
          </Callout>
          <Field label="Name">
            {({ id }) => (
              <Input
                id={id}
                required
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            )}
          </Field>
          <Field
            label="Slug (optional)"
            hint="Used in URLs, e.g. prod-agentos. Derived from the name if empty."
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                mono
                aria-describedby={describedBy}
                value={slug}
                onChange={(event) => {
                  setSlug(event.target.value);
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
          {probe.discovery.auth_mode === "security_key" && (
            <Field
              label="OS security key"
              hint="Stored encrypted. Only Instance admins can use such runtimes."
            >
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  type="password"
                  aria-describedby={describedBy}
                  value={securityKey}
                  onChange={(event) => {
                    setSecurityKey(event.target.value);
                  }}
                />
              )}
            </Field>
          )}
          {connectProblem && (
            <Callout tone="danger">
              {describeError(connectProblem).reason}
              {connectProblem.steps && steps(connectProblem.steps as StepOut[])}
            </Callout>
          )}
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setStage("endpoint");
              }}
            >
              Back
            </Button>
            <Button type="submit" variant="primary" disabled={connect.isPending}>
              {connect.isPending ? "Connecting…" : "Connect and create key pair"}
            </Button>
          </div>
        </form>
      )}

      {stage === "trust" && instance && (
        <TrustStep
          instance={instance}
          onConnected={(connected) => {
            setInstance(connected);
            setStage("done");
          }}
        />
      )}

      {stage === "done" && instance && (
        <Callout
          tone="insight"
          title={`${instance.display_name} is connected`}
          action={
            <div className="flex gap-2">
              <Button asChild variant="primary">
                <Link to="/i/$instance/settings" params={{ instance: instance.slug }}>
                  Open settings
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link to="/access/people">Invite people</Link>
              </Button>
            </div>
          }
        >
          Owners and Administrators have full access to it; give everyone else a role in People.
        </Callout>
      )}
    </div>
  );
}
