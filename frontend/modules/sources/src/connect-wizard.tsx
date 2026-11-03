// Connect source: provider → authentication → repository and branch → path mappings → registry convention → sync
// policy → the initial scan (files found, how each reads, what it matches in Studio, the proposed binding) → start
// syncing. A source that is created keeps scanning in the background; the wizard waits for the report.
import {
  describeError,
  sourcesActivateSource,
  sourcesConnectionBranchesOptions,
  sourcesConnectionReposOptions,
  sourcesCreateConnection,
  sourcesCreateSource,
  sourcesGithubInstall,
  sourcesLocalRootsOptions,
  sourcesScanReportOptions,
  type ConnectionOut,
  type PathMappingIo,
  type SyncPolicyIo,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import {
  Button,
  Callout,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  LoadingRows,
  RadioCards,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PUBLISH_MODES, PULL_MODES, TARGET_LABEL, useConnections, useRefresh } from "./sources-api";

type Provider = "github" | "gitlab" | "gitea" | "forgejo" | "local";
type Stage = "provider" | "auth" | "repo" | "mapping" | "convention" | "policy" | "scan";
const STAGES: readonly { id: Stage; label: string }[] = [
  { id: "provider", label: "Provider" },
  { id: "auth", label: "Authentication" },
  { id: "repo", label: "Repository" },
  { id: "mapping", label: "Paths" },
  { id: "convention", label: "Registry" },
  { id: "policy", label: "Sync" },
  { id: "scan", label: "Scan" },
];

const PROVIDERS: readonly { value: Provider; label: string; description: string }[] = [
  {
    value: "github",
    label: "GitHub",
    description: "GitHub App (read & write) or a token · github.com and Enterprise",
  },
  { value: "gitlab", label: "GitLab", description: "Project or deploy token · gitlab.com and self-managed" },
  { value: "gitea", label: "Gitea", description: "Access token" },
  { value: "forgejo", label: "Forgejo", description: "Access token (the Gitea API)" },
  { value: "local", label: "Local folder", description: "Development instances: writes go straight to disk" },
];

const DEFAULT_MAPPINGS: PathMappingIo[] = [
  { glob: "agents/*.py", target_kind: "agents", writable: true },
  { glob: "teams/*.py", target_kind: "teams", writable: true },
  { glob: "workflows/*.py", target_kind: "workflows", writable: true },
  { glob: "registry.py", target_kind: "registry", writable: false },
  { glob: "tests/, utils/", target_kind: "ignored", writable: false },
];

function Progress({ stage }: { stage: Stage }) {
  const at = STAGES.findIndex((item) => item.id === stage);
  return (
    <ol aria-label="Connect steps" className="flex flex-wrap gap-1.5">
      {STAGES.map((item, index) => (
        <li
          key={item.id}
          aria-current={item.id === stage ? "step" : undefined}
          className={cn(
            "rounded-full border px-2.5 py-0.5 text-[11.5px]",
            item.id === stage
              ? "border-accent text-fg"
              : index < at
                ? "border-border text-fg-secondary"
                : "border-border-subtle text-fg-muted",
          )}
        >
          {item.label}
        </li>
      ))}
    </ol>
  );
}

function ScanReport({
  instance,
  sourceId,
  onActivated,
}: {
  instance: string;
  sourceId: string;
  onActivated: () => void;
}) {
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const report = useQuery({
    ...withQueryFn(sourcesScanReportOptions({ path: { instance, source_id: sourceId } })),
    refetchInterval: (query) => (query.state.data?.status === "scanning" ? 1000 : false),
  });
  const activate = useMutation({
    mutationFn: async (bindings: { path: string; component_id: string; bind: boolean }[]) =>
      (
        await sourcesActivateSource({
          path: { instance, source_id: sourceId },
          body: { bindings },
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      toast.success("Syncing; files that differ from Studio arrive as incoming changes.");
      onActivated();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const data = report.data;
  if (!data || data.status === "scanning" || data.status === "setup") {
    return <LoadingRows rows={4} label="Fetching and reading the repository" />;
  }
  if (data.status === "failed")
    return (
      <Callout tone="danger" title="The scan failed">
        {data.status_detail}
      </Callout>
    );
  const files = (data.report?.files ?? []) as {
    path: string;
    mapping: string;
    components: {
      id: string | null;
      kind: string;
      variable: string;
      parse: string;
      match: string;
      proposed: string;
      diagnostics?: string[];
    }[];
    problems?: string[];
  }[];
  const found = files.flatMap((file) => file.components.map((component) => ({ file, component })));
  const key = (path: string, id: string | null) => `${path}#${id ?? ""}`;
  const MATCH: Record<string, string> = {
    new: "new in Studio",
    same: "matches Studio",
    differs: "differs from Studio",
    none: "no id",
  };
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12.5px] text-fg-secondary">
        {`${String(files.length)} mapped file${files.length === 1 ? "" : "s"} · ${String(found.length)} component${found.length === 1 ? "" : "s"} found`}
      </p>
      <ul aria-label="Scan report" className="flex max-h-80 flex-col gap-1.5 overflow-y-auto">
        {files.map((file) => (
          <li
            key={file.path}
            className="rounded-control border border-border-subtle bg-canvas px-3 py-2 text-[12.5px]"
          >
            <span className="flex items-center gap-2">
              <code className="font-mono">{file.path}</code>
              <span className="text-fg-muted">{TARGET_LABEL[file.mapping] ?? file.mapping}</span>
            </span>
            {file.problems?.map((problem) => (
              <p key={problem} className="text-warning">
                {problem}
              </p>
            ))}
            {file.components.map((component) => (
              <div key={key(file.path, component.id)} className="mt-1 flex items-center gap-2">
                <Checkbox
                  aria-label={`Bind ${component.id ?? component.variable}`}
                  disabled={!component.id || component.proposed === "skip"}
                  checked={component.proposed !== "skip" && !skipped.has(key(file.path, component.id))}
                  onCheckedChange={(checked) => {
                    const next = new Set(skipped);
                    if (checked === true) next.delete(key(file.path, component.id));
                    else next.add(key(file.path, component.id));
                    setSkipped(next);
                  }}
                />
                <code className="font-mono">{component.id ?? component.variable}</code>
                <span className="text-fg-muted">{`${component.kind} · ${component.parse === "ok" ? "reads cleanly" : "has problems"} · ${MATCH[component.match] ?? component.match}`}</span>
              </div>
            ))}
          </li>
        ))}
      </ul>
      <DialogFooter>
        <Button
          variant="primary"
          disabled={activate.isPending}
          onClick={() => {
            activate.mutate(
              found
                .filter(({ component }) => component.id)
                .map(({ file, component }) => ({
                  path: file.path,
                  component_id: component.id ?? "",
                  bind: component.proposed !== "skip" && !skipped.has(key(file.path, component.id)),
                })),
            );
          }}
        >
          Start syncing
        </Button>
      </DialogFooter>
    </div>
  );
}

/** The Connect source dialog; `onClose` gets the new source's id when one was created. */
export function ConnectWizard({
  instance,
  onClose,
}: {
  instance: string;
  onClose: (created?: string) => void;
}) {
  const refresh = useRefresh();
  const [stage, setStage] = useState<Stage>("provider");
  const [provider, setProvider] = useState<Provider>("github");
  const [connectionId, setConnectionId] = useState<string | undefined>(undefined);
  const [newConnection, setNewConnection] = useState({
    name: "",
    web_url: "",
    token: "",
    app: false,
    app_slug: "",
  });
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const [localPath, setLocalPath] = useState("");
  const [mappings, setMappings] = useState<PathMappingIo[]>(DEFAULT_MAPPINGS);
  const [registryModule, setRegistryModule] = useState("app.registry");
  const [policy, setPolicy] = useState<SyncPolicyIo>({ pull_mode: "on_demand", publish_mode: "open_pr" });
  const [sourceId, setSourceId] = useState<string | undefined>(undefined);
  const local = provider === "local";
  const connections = useConnections(!local);
  const matching = (connections.data ?? []).filter(
    (item: ConnectionOut) =>
      item.provider === provider || (provider === "forgejo" && item.provider === "gitea"),
  );
  const roots = useQuery({
    ...withQueryFn(sourcesLocalRootsOptions({ path: { instance } })),
    enabled: local,
    retry: false,
  });
  const repos = useQuery({
    ...withQueryFn(sourcesConnectionReposOptions({ path: { connection_id: connectionId ?? "" } })),
    enabled: Boolean(connectionId) && stage === "repo",
    retry: false,
  });
  const branches = useQuery({
    ...withQueryFn(
      sourcesConnectionBranchesOptions({ path: { connection_id: connectionId ?? "" }, query: { repo } }),
    ),
    enabled: Boolean(connectionId && repo) && stage === "repo",
    retry: false,
  });
  const connect = useMutation({
    mutationFn: async () =>
      (
        await sourcesCreateConnection({
          body: {
            name: newConnection.name.trim()
              ? newConnection.name
              : (PROVIDERS.find((item) => item.value === provider)?.label ?? provider),
            provider: provider as "github" | "gitlab" | "gitea" | "forgejo",
            auth_kind: newConnection.app ? "github_app" : "token",
            web_url: newConnection.web_url || null,
            token: newConnection.app ? null : newConnection.token || null,
            app_slug: newConnection.app ? newConnection.app_slug || null : null,
          },
          throwOnError: true,
        })
      ).data,
    onSuccess: async (created) => {
      setConnectionId(created.id);
      if (created.auth_kind === "github_app") {
        const install = await sourcesGithubInstall({
          path: { connection_id: created.id },
          query: { return_to: `/i/${instance}/studio/sources?connect=1` },
          throwOnError: true,
        });
        window.location.assign(install.data.url);
        return;
      }
      if (created.status !== "verified")
        toast.error(created.last_error ?? "The connection's credentials didn't work.");
      else setStage("repo");
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const create = useMutation({
    mutationFn: async () =>
      (
        await sourcesCreateSource({
          path: { instance },
          body: local
            ? { provider, local_path: localPath, mappings, policy }
            : {
                provider,
                connection_id: connectionId ?? null,
                repo,
                branch,
                mappings,
                policy,
                convention: { registry_module: registryModule },
              },
          throwOnError: true,
        })
      ).data,
    onSuccess: (created) => {
      setSourceId(created.id);
      setStage("scan");
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  const next: Partial<Record<Stage, Stage>> = {
    provider: "auth",
    auth: local ? "mapping" : "repo",
    repo: "mapping",
    mapping: local ? "policy" : "convention",
    convention: "policy",
  };
  const forward = () => {
    const to = next[stage];
    if (to) setStage(to);
  };

  let body;
  switch (stage) {
    case "provider":
      body = (
        <RadioCards
          legend="Where the code lives"
          value={provider}
          onValueChange={setProvider}
          options={PROVIDERS.map(({ value, label, description }) => ({ value, label, description }))}
        />
      );
      break;
    case "auth":
      body = local ? (
        <label className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
          Folder (mounted into Agnostic and the instance)
          <Input
            mono
            value={localPath}
            placeholder={roots.data?.roots[0] ?? "/app"}
            onChange={(event) => {
              setLocalPath(event.target.value);
            }}
          />
          <span className="text-fg-muted">
            {roots.data?.roots.length
              ? `Allowed under ${roots.data.roots.join(", ")}`
              : "Local folders are off here (AGNOSTIC_SOURCES__LOCAL_ROOTS)."}
          </span>
        </label>
      ) : (
        <div className="flex flex-col gap-3">
          {matching.length > 0 && (
            <RadioCards
              legend="Use a connection"
              value={connectionId ?? ""}
              onValueChange={setConnectionId}
              options={matching.map((item) => ({
                value: item.id,
                label: item.name,
                description: `${item.account ?? item.auth_kind} · ${item.status}`,
              }))}
            />
          )}
          <fieldset className="flex flex-col gap-2 rounded-card border border-border-subtle p-3">
            <legend className="px-1 text-[12.5px] text-fg-secondary">Or connect a new one</legend>
            {provider === "github" && (
              <Checkbox
                label="Install the GitHub App (recommended: read & write, least privilege)"
                checked={newConnection.app}
                onCheckedChange={(checked) => {
                  setNewConnection({ ...newConnection, app: checked === true });
                }}
              />
            )}
            {provider !== "github" && (
              <Input
                aria-label="Server URL"
                placeholder={provider === "gitlab" ? "https://gitlab.com" : "https://git.example.com"}
                value={newConnection.web_url}
                onChange={(event) => {
                  setNewConnection({ ...newConnection, web_url: event.target.value });
                }}
              />
            )}
            {newConnection.app ? (
              <Input
                aria-label="App slug"
                placeholder="agnostic-northwind"
                value={newConnection.app_slug}
                onChange={(event) => {
                  setNewConnection({ ...newConnection, app_slug: event.target.value });
                }}
              />
            ) : (
              <Input
                aria-label="Access token"
                placeholder="Access token"
                type="password"
                autoComplete="off"
                value={newConnection.token}
                onChange={(event) => {
                  setNewConnection({ ...newConnection, token: event.target.value });
                }}
              />
            )}
            <Button
              variant="secondary"
              size="30"
              disabled={connect.isPending || (!newConnection.app && !newConnection.token)}
              onClick={() => {
                connect.mutate();
              }}
            >
              {newConnection.app ? "Install on GitHub" : "Connect"}
            </Button>
          </fieldset>
        </div>
      );
      break;
    case "repo":
      body = (
        <div className="flex flex-col gap-3">
          {repos.isError && <Callout tone="danger">{describeError(repos.error).reason}</Callout>}
          <Select value={repo} onValueChange={setRepo}>
            <SelectTrigger aria-label="Repository">
              <SelectValue placeholder={repos.isPending ? "Loading repositories…" : "Pick a repository"} />
            </SelectTrigger>
            <SelectContent>
              {(repos.data ?? []).map((item) => (
                <SelectItem key={item.full_name} value={item.full_name}>
                  {item.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={branch} onValueChange={setBranch}>
            <SelectTrigger aria-label="Branch">
              <SelectValue placeholder="Branch" />
            </SelectTrigger>
            <SelectContent>
              {(branches.data ?? [branch]).map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );
      break;
    case "mapping":
      body = (
        <ul aria-label="Path mappings" className="flex flex-col gap-2">
          {mappings.map((mapping, index) => (
            <li key={String(index)} className="flex items-center gap-2">
              <Input
                mono
                aria-label={`Pattern ${String(index + 1)}`}
                value={mapping.glob}
                onChange={(event) => {
                  setMappings(
                    mappings.map((row, at) => (at === index ? { ...row, glob: event.target.value } : row)),
                  );
                }}
              />
              <span className="w-32 shrink-0 text-[12.5px] text-fg-secondary">
                {TARGET_LABEL[mapping.target_kind]}
              </span>
            </li>
          ))}
        </ul>
      );
      break;
    case "convention":
      body = (
        <label className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
          Where the repository imports registry objects from
          <Input
            mono
            value={registryModule}
            onChange={(event) => {
              setRegistryModule(event.target.value);
            }}
          />
          <span className="text-fg-muted">{`from ${registryModule} import tools, models, knowledge`}</span>
        </label>
      );
      break;
    case "policy":
      body = (
        <div className="flex flex-col gap-3">
          <RadioCards
            legend="Pull from repo"
            value={policy.pull_mode ?? "on_demand"}
            onValueChange={(value) => {
              setPolicy({ ...policy, pull_mode: value });
            }}
            options={PULL_MODES}
          />
          {!local && (
            <RadioCards
              legend="When Studio publishes"
              value={policy.publish_mode ?? "open_pr"}
              onValueChange={(value) => {
                setPolicy({ ...policy, publish_mode: value });
              }}
              options={PUBLISH_MODES}
            />
          )}
        </div>
      );
      break;
    case "scan":
      body = sourceId ? (
        <ScanReport
          instance={instance}
          sourceId={sourceId}
          onActivated={() => {
            refresh();
            onClose(sourceId);
          }}
        />
      ) : null;
      break;
  }

  const canForward =
    (stage === "auth" && (local ? localPath.trim() !== "" : Boolean(connectionId))) ||
    (stage === "repo" && repo !== "" && branch !== "") ||
    stage === "provider" ||
    stage === "mapping" ||
    stage === "convention";

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose(sourceId);
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Connect source</DialogTitle>
          <DialogDescription>
            Pulled changes arrive as drafts; publishes write back as you choose.
          </DialogDescription>
        </DialogHeader>
        <Progress stage={stage} />
        {body}
        {stage !== "scan" && (
          <DialogFooter>
            {stage === "policy" ? (
              <Button
                variant="primary"
                disabled={create.isPending}
                onClick={() => {
                  create.mutate();
                }}
              >
                Connect and scan
              </Button>
            ) : (
              <Button variant="primary" disabled={!canForward} onClick={forward}>
                Continue
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
