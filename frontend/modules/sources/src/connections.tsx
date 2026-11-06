// The org's connections to git hosts: who each acts as and whether its credentials work, with edit (server and API
// URLs, access, a new token or key), verify and remove. Secrets are never shown: a field left empty keeps the old one.
import {
  describeError,
  sourcesDeleteConnection,
  sourcesUpdateConnection,
  sourcesVerifyConnection,
  type ConnectionOut,
  type ConnectionPatchIn,
} from "@agnostic/api";
import { formatRelative } from "@agnostic/core";
import {
  Badge,
  Button,
  Card,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { useConnections, useRefresh } from "./sources-api";

const AUTH_LABEL: Record<string, string> = {
  github_app: "GitHub App",
  token: "Token",
  deploy_key: "Deploy key",
};

const STATUS_TONE: Record<string, "success" | "danger" | "muted"> = {
  verified: "success",
  failed: "danger",
};

export const SERVER_PLACEHOLDER: Record<string, string> = {
  github: "https://github.com (or your GitHub Enterprise server)",
  gitlab: "https://gitlab.com",
  gitea: "https://git.example.com",
  forgejo: "https://git.example.com",
};

/** What a connection says about itself in one line: `GitHub App · read & write · northwind`. */
export function connectionLine(connection: ConnectionOut): string {
  return [
    AUTH_LABEL[connection.auth_kind] ?? connection.auth_kind,
    connection.access === "read_only" ? "pull only" : "read & write",
    connection.account,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The edit form: `secret` is the token, deploy key or GitHub App private key (by the connection's kind). */
export type ConnectionForm = {
  name: string;
  web_url: string;
  api_url: string;
  access: string;
  secret: string;
  app_id?: string;
};

/** The body of a PATCH: only what changed (empty URLs clear, empty secrets keep the old ones). */
export function connectionPatch(connection: ConnectionOut, form: ConnectionForm): ConnectionPatchIn {
  const body: ConnectionPatchIn = { version: connection.version };
  const url = (value: string) => value.trim().replace(/\/+$/, "") || null;
  if (form.name.trim() && form.name.trim() !== connection.name) body.name = form.name.trim();
  if (url(form.web_url) !== (connection.web_url ?? null)) body.web_url = url(form.web_url);
  if (url(form.api_url) !== (connection.api_url ?? null)) body.api_url = url(form.api_url);
  if (form.access !== connection.access)
    body.access = form.access === "read_only" ? "read_only" : "read_write";
  if (form.secret.trim()) {
    if (connection.auth_kind === "deploy_key" || connection.auth_kind === "github_app")
      body.private_key = form.secret;
    else if (connection.auth_kind === "token") body.token = form.secret.trim();
  }
  if (connection.auth_kind === "github_app" && form.app_id?.trim()) body.app_id = form.app_id.trim();
  return body;
}

function EditConnection({ connection, onClose }: { connection: ConnectionOut; onClose: () => void }) {
  const refresh = useRefresh();
  const [form, setForm] = useState({
    name: connection.name,
    web_url: connection.web_url ?? "",
    api_url: connection.api_url ?? "",
    access: connection.access,
    secret: "",
    app_id: "",
  });
  const deployKey = connection.auth_kind === "deploy_key";
  const save = useMutation({
    mutationFn: async () =>
      (
        await sourcesUpdateConnection({
          path: { connection_id: connection.id },
          body: connectionPatch(connection, form),
          throwOnError: true,
        })
      ).data,
    onSuccess: (saved) => {
      refresh();
      if (saved.status === "verified") toast.success(`Saved ${saved.name}; its credentials work.`);
      else toast.error(saved.last_error ?? `Saved ${saved.name}, but its credentials didn't work.`);
      onClose();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => {
    setForm({ ...form, [key]: event.target.value });
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{`Edit ${connection.name}`}</DialogTitle>
          <DialogDescription>
            {`${connection.provider_label} · ${AUTH_LABEL[connection.auth_kind] ?? connection.auth_kind}. Saving checks the credentials again.`}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Name">{({ id }) => <Input id={id} value={form.name} onChange={set("name")} />}</Field>
          <Field
            label="Server URL"
            hint={
              connection.provider === "github"
                ? "Empty for github.com; your server for GitHub Enterprise."
                : connection.provider === "gitlab"
                  ? "Empty for gitlab.com."
                  : undefined
            }
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                mono
                aria-describedby={describedBy}
                placeholder={SERVER_PLACEHOLDER[connection.provider]}
                value={form.web_url}
                onChange={set("web_url")}
              />
            )}
          </Field>
          <Field
            label={deployKey ? "SSH address" : "API URL"}
            hint={
              deployKey
                ? "Only when SSH isn't on port 22 (ssh://git@git.example.com:2222)."
                : "Only when the API isn't at the usual place (…/api/v3, /api/v4, /api/v1)."
            }
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                mono
                aria-describedby={describedBy}
                value={form.api_url}
                onChange={set("api_url")}
              />
            )}
          </Field>
          <Field label="Access">
            {({ id }) => (
              <Select
                value={form.access}
                onValueChange={(value) => {
                  setForm({ ...form, access: value });
                }}
              >
                <SelectTrigger id={id} aria-label="Access">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read_write">Read & write</SelectItem>
                  <SelectItem value="read_only">Pull only (never writes back)</SelectItem>
                </SelectContent>
              </Select>
            )}
          </Field>
          {connection.auth_kind === "token" && (
            <Field label="New token" hint="Leave empty to keep the current one.">
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="off"
                  aria-describedby={describedBy}
                  value={form.secret}
                  onChange={set("secret")}
                />
              )}
            </Field>
          )}
          {connection.auth_kind === "github_app" && (
            <>
              <Field label="New app ID" hint="Leave empty to keep the current one.">
                {({ id, describedBy }) => (
                  <Input
                    id={id}
                    mono
                    aria-describedby={describedBy}
                    value={form.app_id}
                    onChange={set("app_id")}
                  />
                )}
              </Field>
              <Field label="New private key" hint="The app's private key (PEM); leave empty to keep the current one.">
                {({ id, describedBy }) => (
                  <Textarea
                    id={id}
                    rows={4}
                    className="font-mono"
                    aria-describedby={describedBy}
                    value={form.secret}
                    onChange={set("secret")}
                  />
                )}
              </Field>
            </>
          )}
          {connection.auth_kind === "deploy_key" && (
            <Field label="New deploy key" hint="The private key; leave empty to keep the current one.">
              {({ id, describedBy }) => (
                <Textarea
                  id={id}
                  rows={4}
                  className="font-mono"
                  aria-describedby={describedBy}
                  value={form.secret}
                  onChange={set("secret")}
                />
              )}
            </Field>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={save.isPending || !form.name.trim()}
            onClick={() => {
              save.mutate();
            }}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RemoveConnection({ connection, onClose }: { connection: ConnectionOut; onClose: () => void }) {
  const refresh = useRefresh();
  const remove = useMutation({
    mutationFn: async () =>
      sourcesDeleteConnection({ path: { connection_id: connection.id }, throwOnError: true }),
    onSuccess: () => {
      toast.success(`Removed ${connection.name}.`);
      refresh();
      onClose();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{`Remove ${connection.name}?`}</DialogTitle>
          <DialogDescription>
            Its credentials are deleted. Sources that still use it have to be disconnected first.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive-outline"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate();
            }}
          >
            Remove
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The Connections card: every connection to a git host, for the whole org. */
export function ConnectionsCard({ canEdit, canDelete }: { canEdit: boolean; canDelete: boolean }) {
  const connections = useConnections();
  const refresh = useRefresh();
  const [editing, setEditing] = useState<ConnectionOut | undefined>(undefined);
  const [removing, setRemoving] = useState<ConnectionOut | undefined>(undefined);
  const verify = useMutation({
    mutationFn: async (connection: ConnectionOut) =>
      (await sourcesVerifyConnection({ path: { connection_id: connection.id }, throwOnError: true })).data,
    onSuccess: (checked) => {
      refresh();
      if (checked.status === "verified") toast.success(`${checked.name} works.`);
      else toast.error(checked.last_error ?? `${checked.name}'s credentials didn't work.`);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const list = connections.data ?? [];
  return (
    <Card title="Connections">
      {connections.isPending ? (
        <LoadingRows rows={2} label="Loading the connections" />
      ) : connections.isError ? (
        <ErrorState {...describeError(connections.error)} onRetry={() => void connections.refetch()} />
      ) : list.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">No connections yet; Connect source adds one.</p>
      ) : (
        <ul aria-label="Connections" className="flex flex-col gap-2">
          {list.map((connection) => (
            <li
              key={connection.id}
              aria-label={connection.name}
              className="flex flex-col gap-1 rounded-control border border-border-subtle px-3 py-2 text-[12.5px]"
            >
              <span className="flex items-center gap-2">
                <span className="font-medium">{connection.name}</span>
                <span className="text-fg-muted">{connection.provider_label}</span>
                <span className="flex-1" />
                <Badge tone={STATUS_TONE[connection.status] ?? "muted"}>{connection.status}</Badge>
              </span>
              <span className="text-fg-secondary">{connectionLine(connection)}</span>
              {connection.web_url && (
                <span className="truncate font-mono text-[11.5px] text-fg-muted">{connection.web_url}</span>
              )}
              {connection.status === "failed" && connection.last_error && (
                <span className="text-danger">{connection.last_error}</span>
              )}
              <span className="flex flex-wrap items-center gap-1">
                {connection.last_checked_at && (
                  <span className="text-[11.5px] text-fg-muted">{`checked ${formatRelative(connection.last_checked_at)}`}</span>
                )}
                <span className="flex-1" />
                {canEdit && (
                  <>
                    <Button
                      variant="ghost"
                      size="28"
                      aria-label={`Verify ${connection.name}`}
                      disabled={verify.isPending}
                      onClick={() => {
                        verify.mutate(connection);
                      }}
                    >
                      Verify
                    </Button>
                    <Button
                      variant="ghost"
                      size="28"
                      aria-label={`Edit ${connection.name}`}
                      onClick={() => {
                        setEditing(connection);
                      }}
                    >
                      Edit
                    </Button>
                  </>
                )}
                {canDelete && (
                  <Button
                    variant="ghost"
                    size="28"
                    aria-label={`Remove ${connection.name}`}
                    onClick={() => {
                      setRemoving(connection);
                    }}
                  >
                    Remove
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <EditConnection
          connection={editing}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
      {removing && (
        <RemoveConnection
          connection={removing}
          onClose={() => {
            setRemoving(undefined);
          }}
        />
      )}
    </Card>
  );
}
