// Connect source: provider → authentication → repository and branch → path mappings → registry convention → sync
// policy → the initial scan (files found, how each reads, what it matches in Studio, the proposed binding) → start
// syncing. A source that is created keeps scanning in the background; the wizard waits for the report, and a source
// left at its scan finishes from its page (`ScanReportDialog`). Back from installing the GitHub App, the wizard picks
// up at the repository with the new connection.
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
import { useEffect, useState } from "react";

import { SERVER_PLACEHOLDER } from "./connections";
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

const GITEA_FAMILY: readonly string[] = ["gitea", "forgejo"];
const REPO_NAME = /^[\w.-]+(\/[\w.-]+){1,5}$/;
const MODULE = /^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$/;
const IDENTIFIER = /^[A-Za-z_]\w*$/;

/** The package a local folder most likely is: its own name (`/srv/app` → `app`), else the reference runtime's. */
export function folderPackage(path: string): string {
  const name = path.replace(/\/+$/, "").split("/").pop() ?? "";
  return IDENTIFIER.test(name) ? name : "app";
}

/** Every module the convention names, under one package (`app` → `app.agents`, `app.registry`, …). */
export function conventionFor(pkg: string, registryModule?: string) {
  return {
    registry_module: registryModule ?? `${pkg}.registry`,
    agents_module: `${pkg}.agents`,
    teams_module: `${pkg}.teams`,
    workflows_module: `${pkg}.workflows`,
    functions_module: `${pkg}.functions`,
  };
}

/** Connections a provider's source may use: its own, and Gitea's and Forgejo's for each other (same API). */
export function usable(connection: ConnectionOut, provider: Provider): boolean {
  return (
    connection.provider === provider ||
    (GITEA_FAMILY.includes(provider) && GITEA_FAMILY.includes(connection.provider))
  );
}

/** `value`, once it has stopped changing for `delay` ms (search as you type without a request per key). */
function useDebounced<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSettled(value);
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delay]);
  return settled;
}

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

/** The initial scan of a source, and "Start syncing" with the bindings the user kept. */
export function ScanReport({
  instance,
  sourceId,
  root,
  onActivated,
}: {
  instance: string;
  sourceId: string;
  /** The folder or repository the mappings are relative to, for the message when they take no file. */
  root: string;
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
  const { listed, unmapped } = data.report ?? {};
  const key = (path: string, id: string | null) => `${path}#${id ?? ""}`;
  if (files.length === 0) {
    return (
      <Callout tone="warning" title="No file matches the path mappings">
        <p>
          {`The mappings are relative to ${root}${typeof listed === "number" ? `, which holds ${String(listed)} file${listed === 1 ? "" : "s"}` : ""}, and take none of them, so there is nothing to sync yet.`}
        </p>
        {Array.isArray(unmapped) && unmapped.length > 0 && (
          <>
            <p className="mt-2">Python files no mapping takes:</p>
            <ul aria-label="Unmapped files" className="mt-1 flex flex-col gap-0.5">
              {(unmapped as string[]).map((path) => (
                <li key={path}>
                  <code className="font-mono">{path}</code>
                </li>
              ))}
            </ul>
          </>
        )}
        <p className="mt-2">
          Edit the patterns under Path mapping on the source's page; Studio scans again, and you start syncing from
          there.
        </p>
      </Callout>
    );
  }
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

/** The scan of a source that was connected but never started syncing, opened again from the source's page. */
export function ScanReportDialog({
  instance,
  sourceId,
  root,
  onClose,
}: {
  instance: string;
  sourceId: string;
  root: string;
  onClose: () => void;
}) {
  const refresh = useRefresh();
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Scan report</DialogTitle>
          <DialogDescription>
            Bind the files Studio found and start syncing; nothing moves until then.
          </DialogDescription>
        </DialogHeader>
        <ScanReport
          instance={instance}
          sourceId={sourceId}
          root={root}
          onActivated={() => {
            refresh();
            onClose();
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

/** The Connect source dialog; `onClose` gets the new source's id when one was created. */
export function ConnectWizard({
  instance,
  resumeConnection,
  onClose,
}: {
  instance: string;
  /** A GitHub App connection that was just installed (so the provider is GitHub): start at the repository step. */
  resumeConnection?: string | undefined;
  onClose: (created?: string) => void;
}) {
  const refresh = useRefresh();
  const [stage, setStage] = useState<Stage>(resumeConnection ? "repo" : "provider");
  const [provider, setProvider] = useState<Provider>("github");
  const [connectionId, setConnectionId] = useState<string | undefined>(resumeConnection);
  const [newConnection, setNewConnection] = useState({
    name: "",
    web_url: "",
    api_url: "",
    token: "",
    app: false,
    app_slug: "",
  });
  const [repoQuery, setRepoQuery] = useState("");
  const query = useDebounced(repoQuery.trim());
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const [localPath, setLocalPath] = useState("");
  const [mappings, setMappings] = useState<PathMappingIo[]>(DEFAULT_MAPPINGS);
  // Unset, the package follows the folder's name and the registry module follows the package.
  const [pkg, setPkg] = useState<string | undefined>(undefined);
  const [registryModule, setRegistryModule] = useState<string | undefined>(undefined);
  const [policy, setPolicy] = useState<SyncPolicyIo>({ pull_mode: "on_demand", publish_mode: "open_pr" });
  const [sourceId, setSourceId] = useState<string | undefined>(undefined);
  const local = provider === "local";
  const packageName = pkg ?? (local ? folderPackage(localPath) : "app");
  const convention = conventionFor(packageName, registryModule);
  const connections = useConnections(!local);
  const matching = (connections.data ?? []).filter((item: ConnectionOut) => usable(item, provider));
  const roots = useQuery({
    ...withQueryFn(sourcesLocalRootsOptions({ path: { instance } })),
    enabled: local,
    retry: false,
  });
  const repos = useQuery({
    ...withQueryFn(
      sourcesConnectionReposOptions({
        path: { connection_id: connectionId ?? "" },
        query: { q: query || null },
      }),
    ),
    enabled: Boolean(connectionId) && stage === "repo",
    retry: false,
  });
  const found = (repos.data ?? []).map((item) => item.full_name);
  // A repository the list can't show (a deploy key lists nothing): use the name as typed.
  const typed = REPO_NAME.test(query) && !found.includes(query) ? [query] : [];
  const choices = [...new Set([...found, ...typed, ...(repo ? [repo] : [])])];
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
            web_url: newConnection.web_url.trim() || null,
            api_url: provider === "github" ? newConnection.api_url.trim() || null : null,
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
          query: {
            return_to: `/i/${instance}/studio/sources?connect=1&connection=${encodeURIComponent(created.id)}`,
          },
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
            ? { provider, local_path: localPath, mappings, policy, convention }
            : {
                provider,
                connection_id: connectionId ?? null,
                repo,
                branch,
                mappings,
                policy,
                convention,
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
    mapping: "convention",
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
            <Input
              aria-label="Server URL"
              placeholder={SERVER_PLACEHOLDER[provider]}
              value={newConnection.web_url}
              onChange={(event) => {
                setNewConnection({ ...newConnection, web_url: event.target.value });
              }}
            />
            {provider === "github" && (
              <Input
                aria-label="API URL"
                placeholder="API URL (GitHub Enterprise, when it isn't …/api/v3)"
                value={newConnection.api_url}
                onChange={(event) => {
                  setNewConnection({ ...newConnection, api_url: event.target.value });
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
          <Input
            type="search"
            aria-label="Search repositories"
            placeholder="Search repositories, or type owner/name"
            value={repoQuery}
            onChange={(event) => {
              setRepoQuery(event.target.value);
            }}
          />
          <Select value={repo} onValueChange={setRepo}>
            <SelectTrigger aria-label="Repository">
              <SelectValue
                placeholder={
                  repos.isFetching
                    ? "Loading repositories…"
                    : choices.length
                      ? "Pick a repository"
                      : "No repositories match"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {choices.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
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
        <div className="flex flex-col gap-2">
          <p className="text-[12.5px] text-fg-secondary">
            {`Patterns are relative to ${local ? localPath || "the folder" : "the repository's root"}.`}
          </p>
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
        </div>
      );
      break;
    case "convention":
      body = (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
            The Python package the agents, teams and workflows live in
            <Input
              mono
              value={packageName}
              onChange={(event) => {
                setPkg(event.target.value);
              }}
            />
            <span className="text-fg-muted">
              {`Studio writes imports like from ${convention.agents_module} import …`}
            </span>
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
            Where the code imports registry objects from
            <Input
              mono
              value={convention.registry_module}
              onChange={(event) => {
                setRegistryModule(event.target.value);
              }}
            />
            <span className="text-fg-muted">{`from ${convention.registry_module} import tools, models, knowledge`}</span>
          </label>
        </div>
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
          root={local ? localPath : repo}
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
    (stage === "convention" && MODULE.test(packageName) && MODULE.test(convention.registry_module));

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
