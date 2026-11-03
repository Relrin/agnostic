// The resource × action matrix of a role: catalogued cells are checkboxes, the rest "—"; changed cells are tinted.
// Agents, teams and workflows with Run checked get a "Run applies to" row (all, or selected components).
import { Button, Input, SegmentedControl, cn } from "@agnostic/ui";
import { Plus, X } from "lucide-react";
import { useState } from "react";

import {
  MATRIX_ACTIONS,
  RUN_RESOURCES,
  RUN_SINGULAR,
  cellName,
  has,
  runScopeChanged,
  type MatrixGroup,
  type Permissions,
  type RoleDraft,
  type RunChoice,
  type RunResource,
  withCell,
} from "./roles-api";

const CHANGED = "bg-accent/9";

function isRunResource(family: string): family is RunResource {
  return (RUN_RESOURCES as readonly string[]).includes(family);
}

function Check({
  label,
  checked,
  disabled,
  title,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  title: string;
  onChange: (next: boolean) => void;
}) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      title={title}
      className="size-4 cursor-pointer accent-[var(--accent)] disabled:cursor-default"
      checked={checked}
      disabled={disabled}
      onChange={(event) => {
        onChange(event.target.checked);
      }}
    />
  );
}

/** Chips of component ids with an input to add more (`support-triage`, `billing-agent`). */
function ComponentChips({
  resource,
  ids,
  disabled,
  onChange,
}: {
  resource: RunResource;
  ids: string[];
  disabled: boolean;
  onChange: (next: string[]) => void;
}) {
  const [text, setText] = useState("");
  const singular = RUN_SINGULAR[resource];
  const add = () => {
    const fresh = text
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item && !ids.includes(item));
    if (fresh.length) onChange([...ids, ...fresh]);
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {ids.map((id) => (
        <span
          key={id}
          className="inline-flex h-[26px] items-center gap-1 rounded-full border border-border-strong bg-surface pr-1 pl-2.5 font-mono text-[12px]"
        >
          {id}
          {!disabled && (
            <button
              type="button"
              aria-label={`Remove ${id}`}
              className="grid size-5 cursor-pointer place-items-center rounded-full text-fg-muted hover:bg-surface-hover hover:text-fg"
              onClick={() => {
                onChange(ids.filter((item) => item !== id));
              }}
            >
              <X aria-hidden className="size-3" />
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <span className="inline-flex items-center gap-1">
          <Input
            mono
            aria-label={`Add ${singular} id`}
            placeholder={`${singular} id`}
            className="h-[26px] w-36 text-[12px]"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                add();
              }
            }}
          />
          <Button variant="dashed-add" size="28" disabled={!text.trim()} onClick={add}>
            <Plus aria-hidden />
            Add {singular}
          </Button>
        </span>
      )}
      {ids.length === 0 && (
        <span className="text-[12px] text-warning">Add at least one {singular}, or let it run all.</span>
      )}
    </div>
  );
}

function RunAppliesTo({
  resource,
  base,
  draft,
  disabled,
  onChange,
}: {
  resource: RunResource;
  base: RoleDraft;
  draft: RoleDraft;
  disabled: boolean;
  onChange: (choice: RunChoice) => void;
}) {
  const choice = draft.runScope[resource];
  const changed = runScopeChanged(base, draft, resource);
  return (
    <tr className={cn("border-b border-divider-row", changed && CHANGED)}>
      <td colSpan={5} className="py-2 pr-3 pl-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-[12.5px] text-fg-secondary">Run applies to</span>
          <SegmentedControl
            size="mini"
            label={`${resource} run applies to`}
            value={choice === "all" ? "all" : "selected"}
            options={[
              { value: "all", label: `All ${resource}`, disabled },
              { value: "selected", label: `Selected ${resource}`, disabled },
            ]}
            onValueChange={(next) => {
              onChange(next === "all" ? "all" : choice === "all" ? [] : choice);
            }}
          />
          {choice !== "all" && (
            <ComponentChips
              resource={resource}
              ids={choice}
              disabled={disabled}
              onChange={(ids) => {
                onChange(ids);
              }}
            />
          )}
        </div>
        {choice !== "all" && (
          <p className="mt-1.5 font-mono text-[11.5px] text-fg-muted">
            {resource}:run becomes one {resource}:&lt;id&gt;:run per {RUN_SINGULAR[resource]}.
          </p>
        )}
      </td>
    </tr>
  );
}

export function PermissionMatrix({
  roleName,
  groups,
  base,
  draft,
  disabled,
  changed,
  onPermissions,
  onRunScope,
}: {
  roleName: string;
  groups: MatrixGroup[];
  base: RoleDraft;
  draft: RoleDraft;
  disabled: boolean;
  changed: Set<string>;
  onPermissions: (next: Permissions) => void;
  onRunScope: (resource: RunResource, choice: RunChoice) => void;
}) {
  const toggle = (family: string, action: string, on: boolean) => {
    onPermissions(withCell(draft.permissions, family, action, on));
  };
  return (
    <div className="min-w-0 overflow-x-auto rounded-tile border border-border">
      <table
        aria-label={`${roleName} permissions`}
        className="w-full min-w-[520px] border-collapse text-[13px]"
      >
        <thead>
          <tr className="border-b border-border text-left font-mono text-[10.5px] tracking-[0.08em] text-fg-muted uppercase">
            <th scope="col" className="px-3 py-2 font-medium">
              Resource
            </th>
            {MATRIX_ACTIONS.map((action) => (
              <th key={action} scope="col" className="w-[76px] py-2 text-center font-medium">
                {action}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.id}>
            <tr className="border-b border-divider-row bg-inset">
              <th
                scope="colgroup"
                colSpan={5}
                className="px-3 py-1.5 text-left font-mono text-[10.5px] font-medium tracking-[0.08em] text-fg-muted uppercase"
              >
                {group.label}
              </th>
            </tr>
            {group.rows.map((row) => {
              if (row.kind === "extra") {
                const scope = row.spec.scope;
                const on = has(draft.permissions, row.family, row.spec.action);
                return (
                  <tr key={scope} className="border-b border-divider-row">
                    <th scope="row" className="px-3 py-2 text-left font-normal">
                      <span className="block text-[13px] font-medium">{row.label}</span>
                      <code className="font-mono text-[11.5px] text-fg-muted">{scope}</code>
                    </th>
                    <td colSpan={4} className={cn("px-3 py-2", changed.has(scope) && CHANGED)}>
                      <label className="inline-flex items-center gap-2 text-[12.5px] text-fg-secondary">
                        <Check
                          label={`${roleName}: ${cellName(row.family, row.spec.action)}`}
                          title={row.spec.description}
                          checked={on}
                          disabled={disabled}
                          onChange={(next) => {
                            toggle(row.family, row.spec.action, next);
                          }}
                        />
                        <span className="font-mono">{row.spec.action}</span>
                        {row.spec.privileged && (
                          <span className="text-[11.5px] text-warning">privileged</span>
                        )}
                      </label>
                    </td>
                  </tr>
                );
              }
              const runResource = isRunResource(row.family) ? row.family : undefined;
              return [
                <tr key={row.family} className="border-b border-divider-row">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="block text-[13px] font-medium">{row.label}</span>
                    <code className="font-mono text-[11.5px] text-fg-muted">{row.family}</code>
                  </th>
                  {MATRIX_ACTIONS.map((action) => {
                    const spec = row.cells[action];
                    const scope = `${row.family}:${action}`;
                    return (
                      <td
                        key={action}
                        className={cn("py-2 text-center align-middle", changed.has(scope) && CHANGED)}
                      >
                        {spec ? (
                          <Check
                            label={`${roleName}: ${cellName(row.family, action)}`}
                            title={spec.description}
                            checked={has(draft.permissions, row.family, action)}
                            disabled={disabled}
                            onChange={(next) => {
                              toggle(row.family, action, next);
                            }}
                          />
                        ) : (
                          <span title="Not applicable" className="text-fg-disabled">
                            <span aria-hidden>—</span>
                            <span className="sr-only">Not applicable</span>
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>,
                runResource && has(draft.permissions, row.family, "run") ? (
                  <RunAppliesTo
                    key={`${row.family}:run-scope`}
                    resource={runResource}
                    base={base}
                    draft={draft}
                    disabled={disabled}
                    onChange={(choice) => {
                      onRunScope(runResource, choice);
                    }}
                  />
                ) : null,
              ];
            })}
          </tbody>
        ))}
      </table>
    </div>
  );
}
