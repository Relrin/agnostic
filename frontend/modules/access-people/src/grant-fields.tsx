// What a binding grants: an access role, or explicit scopes from the catalog (optionally narrowed to one agent, team
// or workflow), on one instance or all of them. Shared by "Add direct role", group bindings and temporary access.
import { accessListScopesOptions, describeError, type InstanceOut, type RoleOut } from "@agnostic/api";
import { STALE_TIME, withQueryFn } from "@agnostic/core";
import {
  Input,
  LoadingRows,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { useId } from "react";

import { ALL } from "./people-api";

export type GrantDraft = {
  mode: "role" | "scopes";
  roleId: string;
  scopes: string[];
  /** Narrows per-component scopes (`agents:run` → `agents:billing-agent:run`). */
  component: string;
  /** An instance id, or `ALL`. */
  instance: string;
};

export function emptyDraft(roles: readonly RoleOut[], instances: readonly InstanceOut[]): GrantDraft {
  return {
    mode: "role",
    roleId: roles.find((role) => role.slug === "viewer")?.id ?? roles[0]?.id ?? "",
    scopes: [],
    component: "",
    instance: instances[0]?.id ?? ALL,
  };
}

const PER_COMPONENT = new Set(["agents", "teams", "workflows"]);

/** The scopes as sent: per-component ones narrowed to the component when one is given. */
export function draftScopes(draft: GrantDraft): string[] {
  const component = draft.component.trim();
  return draft.scopes.map((scope) => {
    const [family, action] = scope.split(":");
    return component && family && action && PER_COMPONENT.has(family)
      ? `${family}:${component}:${action}`
      : scope;
  });
}

/** The grant part of a binding or temporary access body. */
export function draftGrant(draft: GrantDraft): {
  role_id: string | null;
  scopes: string[];
  instance: string | null;
} {
  return {
    role_id: draft.mode === "role" ? draft.roleId || null : null,
    scopes: draft.mode === "scopes" ? draftScopes(draft) : [],
    instance: draft.instance === ALL ? null : draft.instance,
  };
}

export function draftReady(draft: GrantDraft): boolean {
  return draft.mode === "role" ? Boolean(draft.roleId) : draft.scopes.length > 0;
}

function ScopePicker({ draft, onChange }: { draft: GrantDraft; onChange: (next: GrantDraft) => void }) {
  const scopes = useQuery({ ...withQueryFn(accessListScopesOptions()), staleTime: STALE_TIME.config });
  const componentId = useId();
  if (scopes.isPending) return <LoadingRows rows={2} label="Loading scopes" />;
  if (scopes.isError)
    return <p className="text-[12.5px] text-danger">{describeError(scopes.error).reason}</p>;
  const visible = scopes.data.filter((scope) => !scope.hidden);
  const families = [...new Set(visible.map((scope) => scope.family))];
  const narrowable = draft.scopes.some((scope) => PER_COMPONENT.has(scope.split(":")[0] ?? ""));
  const toggle = (scope: string) => {
    onChange({
      ...draft,
      scopes: draft.scopes.includes(scope)
        ? draft.scopes.filter((item) => item !== scope)
        : [...draft.scopes, scope],
    });
  };
  return (
    <div className="flex flex-col gap-2">
      <fieldset className="flex max-h-48 flex-col gap-1.5 overflow-y-auto rounded-tile border border-border p-2.5">
        <legend className="sr-only">Scopes</legend>
        {families.map((family) => (
          <div key={family} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="w-24 shrink-0 font-mono text-[11.5px] text-fg-muted">{family}</span>
            {visible
              .filter((scope) => scope.family === family)
              .map((scope) => (
                <label
                  key={scope.scope}
                  title={scope.description}
                  className="flex cursor-pointer items-center gap-1.5 font-mono text-[12px]"
                >
                  <input
                    type="checkbox"
                    className="size-3.5 accent-[var(--accent)]"
                    aria-label={scope.scope}
                    checked={draft.scopes.includes(scope.scope)}
                    onChange={() => {
                      toggle(scope.scope);
                    }}
                  />
                  {scope.action}
                </label>
              ))}
          </div>
        ))}
      </fieldset>
      {narrowable && (
        <div className="flex items-center gap-2">
          <label htmlFor={componentId} className="text-[12.5px] whitespace-nowrap text-fg-secondary">
            Only for
          </label>
          <Input
            id={componentId}
            mono
            className="h-8"
            placeholder="any agent, team or workflow"
            value={draft.component}
            onChange={(event) => {
              onChange({ ...draft, component: event.target.value });
            }}
          />
        </div>
      )}
    </div>
  );
}

export function GrantFields({
  draft,
  onChange,
  roles,
  instances,
  allowAll = true,
}: {
  draft: GrantDraft;
  onChange: (next: GrantDraft) => void;
  roles: readonly RoleOut[];
  instances: readonly InstanceOut[];
  allowAll?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl
          label="Grant"
          size="mini"
          value={draft.mode}
          options={[
            { value: "role", label: "Role" },
            { value: "scopes", label: "Scopes" },
          ]}
          onValueChange={(mode) => {
            onChange({ ...draft, mode });
          }}
        />
        <Select
          value={draft.instance}
          onValueChange={(instance) => {
            onChange({ ...draft, instance });
          }}
        >
          <SelectTrigger aria-label="Instance" className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {instances.map((instance) => (
              <SelectItem key={instance.id} value={instance.id}>
                {instance.slug}
              </SelectItem>
            ))}
            {allowAll && <SelectItem value={ALL}>All instances</SelectItem>}
          </SelectContent>
        </Select>
        {draft.mode === "role" && (
          <Select
            value={draft.roleId}
            onValueChange={(roleId) => {
              onChange({ ...draft, roleId });
            }}
          >
            <SelectTrigger aria-label="Role" className="h-8 w-44">
              <SelectValue placeholder="Choose a role" />
            </SelectTrigger>
            <SelectContent>
              {roles.map((role) => (
                <SelectItem key={role.id} value={role.id}>
                  {role.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      {draft.mode === "scopes" && <ScopePicker draft={draft} onChange={onChange} />}
    </div>
  );
}
