// The config form: schema-driven sections (one accordion each, with a one-line summary while closed), a control per
// field widget, registry pickers, "Changed from X in vN" hints and L8 line-link badges into the code pane.
import type { RegistryEntryOut, SpanOut } from "@agnostic/api";
import {
  Accordion,
  AccordionSection,
  Badge,
  Button,
  Combobox,
  Input,
  JsonEditor,
  LineLinkBadge,
  ModelMark,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SortableList,
  Switch,
  Textarea,
  cn,
} from "@agnostic/ui";
import { Plus, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import {
  display,
  instructions,
  isRecord,
  modelId,
  refName,
  same,
  tools,
  withField,
  type Config,
  type ToolEntry,
} from "./config";
import type { FieldInfo, Section } from "./document";
import { sectionSummary } from "./summaries";
import { ToolCard, ToolPicker } from "./tool-blocks";

const OPEN_BY_DEFAULT = new Set(["model", "instructions", "tools", "team", "members"]);
const REF_KEYS: Record<string, string> = {
  knowledge: "name",
  learning: "name",
  memory_manager: "registry_id",
};
const REF_TYPES: Record<string, string> = {
  model: "model",
  knowledge: "knowledge",
  schema: "schema",
  memory_manager: "memory_manager",
  learning: "learning",
};

export type FormContext = {
  config: Config;
  onChange: (update: (config: Config) => Config) => void;
  /** The version the draft is compared with (for "Changed from X in vN" and "new" markers). */
  base?: { version: number; config: Config | null } | undefined;
  spans: Record<string, SpanOut>;
  focusedPath: string | undefined;
  onFocusPath: (path: string | undefined) => void;
  registry: {
    byType: (type: string) => RegistryEntryOut[];
    find: (type: string, name: string) => RegistryEntryOut | undefined;
  };
  readOnly?: boolean | undefined;
  /** The instance the component is on (the tool picker sets custom tools up for it). */
  instance?: string | undefined;
  /** Fields set in code in a way the form can't edit: shown read-only with a way to the code. */
  isCodeOwned?: ((path: string) => boolean) | undefined;
  onEditInCode?: ((path: string) => void) | undefined;
};

export function fieldId(path: string): string {
  return `field-${path.replace(/[[\].]/g, "-")}`;
}

/** The base value differs: "Changed from 0.7 in v3" (or "New since v3"). */
function ChangedHint({ name, ctx }: { name: string; ctx: FormContext }) {
  const base = ctx.base;
  if (!base?.config) return null;
  const before = base.config[name];
  const after = ctx.config[name];
  if (same(before, after) || Array.isArray(after)) return null;
  return (
    <p className="text-[11.5px] text-fg-muted">
      {before === undefined
        ? `New since v${String(base.version)}`
        : `Changed from ${display(before)} in v${String(base.version)}`}
    </p>
  );
}

function LineLink({ path, ctx }: { path: string; ctx: FormContext }) {
  const span = ctx.spans[path];
  if (!span) return null;
  return (
    <LineLinkBadge
      line={span.line}
      active={ctx.focusedPath === path}
      onClick={() => {
        ctx.onFocusPath(ctx.focusedPath === path ? undefined : path);
      }}
    />
  );
}

function FieldFrame({
  name,
  info,
  ctx,
  children,
  inline = false,
}: {
  name: string;
  info: FieldInfo;
  ctx: FormContext;
  children: (id: string) => ReactNode;
  inline?: boolean;
}) {
  const id = fieldId(name);
  const focused = ctx.focusedPath === name;
  return (
    <div
      className={cn("flex flex-col gap-1.5 rounded-control", focused && "ring-[3px] ring-accent/14")}
      onFocus={() => {
        if (ctx.spans[name]) ctx.onFocusPath(name);
      }}
    >
      {!inline && (
        <div className="flex items-center gap-2">
          <label htmlFor={id} className="text-[12.5px] font-medium text-fg-secondary">
            {info.label}
          </label>
          {info.legacy && <Badge tone="warning">legacy</Badge>}
          <span className="flex-1" />
          <LineLink path={name} ctx={ctx} />
        </div>
      )}
      {children(id)}
      {inline && <LineLink path={name} ctx={ctx} />}
      {info.help && !inline && <p className="text-[11.5px] text-fg-muted">{info.help}</p>}
      <ChangedHint name={name} ctx={ctx} />
    </div>
  );
}

function RegistrySelect({
  id,
  type,
  value,
  onChange,
  ctx,
  label,
}: {
  id: string;
  type: string;
  value: string | undefined;
  onChange: (entry: RegistryEntryOut | undefined) => void;
  ctx: FormContext;
  label: string;
}) {
  const entries = ctx.registry.byType(type).filter((entry) => entry.studio_available);
  const NONE = "__none__";
  return (
    <Combobox
      id={id}
      aria-label={label}
      mono
      value={value ?? NONE}
      disabled={ctx.readOnly ?? false}
      placeholder="None"
      searchPlaceholder={`Search ${label.toLowerCase()}…`}
      emptyText={`Nothing of this kind is registered on this instance.`}
      group="From Registry"
      options={[
        { value: NONE, label: "None" },
        ...entries.map((entry) => ({
          value: entry.id ?? entry.name,
          label: entry.name,
          hint: entry.meta,
          icon: type === "model" ? <EntryModelMark entry={entry} /> : undefined,
        })),
      ]}
      onValueChange={(next) => {
        onChange(next === NONE ? undefined : entries.find((entry) => (entry.id ?? entry.name) === next));
      }}
    />
  );
}

/** A model entry's provider logo (its config is the stored model ref: `{id, provider}`). */
function EntryModelMark({ entry }: { entry: RegistryEntryOut }) {
  const ref = isRecord(entry.config_value) ? entry.config_value : {};
  return (
    <ModelMark
      provider={typeof ref.provider === "string" ? ref.provider : undefined}
      id={typeof ref.id === "string" ? ref.id : (entry.id ?? entry.name)}
      className="text-fg-secondary"
    />
  );
}

function ModelField({ name, ctx }: { name: string; ctx: FormContext }) {
  const current = modelId(ctx.config[name]);
  const entry = current ? ctx.registry.find("model", current) : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <RegistrySelect
        id={fieldId(name)}
        type="model"
        label="Model"
        value={current}
        ctx={ctx}
        onChange={(picked) => {
          ctx.onChange((config) => withField(config, name, picked?.config_value ?? undefined));
        }}
      />
      {current && (
        <p className={cn("font-mono text-[11.5px]", entry ? "text-fg-muted" : "text-danger")}>
          {entry ? entry.meta : `${current} isn't registered on this instance.`}
        </p>
      )}
    </div>
  );
}

let rows = 0;

function rowId(): string {
  rows += 1;
  return `instruction-${String(rows)}`;
}

function resized(ids: readonly string[], length: number): string[] {
  const next = ids.slice(0, length);
  while (next.length < length) next.push(rowId());
  return next;
}

function InstructionsField({ name, ctx }: { name: string; ctx: FormContext }) {
  const items = instructions(ctx.config);
  const before = ctx.base?.config ? instructions(ctx.base.config) : undefined;
  // Stable row ids, so typing in a row (which changes its text) never remounts it; they follow reorders.
  const [stored, setIds] = useState<string[]>(() => items.map(rowId));
  const ids = stored.length === items.length ? stored : resized(stored, items.length);
  if (ids !== stored) setIds(ids);
  const keyed = items.map((value, index) => ({ key: ids[index] ?? String(index), value, index }));
  const update = (next: string[], order?: string[]) => {
    if (order) setIds(order);
    ctx.onChange((config) => withField(config, name, next.length ? next : undefined));
  };
  return (
    <div className="flex flex-col gap-1.5">
      <SortableList
        aria-label="Instructions"
        items={keyed}
        getId={(item) => item.key}
        getLabel={(item) => item.value || `Instruction ${String(item.index + 1)}`}
        disabled={ctx.readOnly ?? false}
        onReorder={(next) => {
          update(
            next.map((item) => item.value),
            next.map((item) => item.key),
          );
        }}
        renderItem={(item, state) => {
          const fresh = before !== undefined && !before.includes(item.value);
          const path = `${name}[${String(state.index)}]`;
          return (
            <div
              className={cn(
                "flex items-start gap-2 rounded-[7px] border bg-inset px-2 py-1.5",
                fresh ? "border-accent/40 bg-accent/5" : "border-border-input",
                ctx.focusedPath === path && "ring-[3px] ring-accent/14",
              )}
            >
              {state.handle}
              <Textarea
                id={fieldId(path)}
                aria-label={`Instruction ${String(state.index + 1)}`}
                rows={1}
                className="[field-sizing:content] min-h-0 flex-1 resize-none border-0 bg-transparent p-0 text-[12.5px]"
                value={item.value}
                readOnly={ctx.readOnly ?? false}
                onFocus={() => {
                  if (ctx.spans[path]) ctx.onFocusPath(path);
                }}
                onChange={(event) => {
                  const next = [...items];
                  next[state.index] = event.target.value;
                  update(next);
                }}
              />
              {fresh && <span className="font-mono text-[10.5px] text-accent">new</span>}
              <LineLink path={path} ctx={ctx} />
              {!ctx.readOnly && (
                <Button
                  variant="icon"
                  size="28"
                  aria-label={`Remove instruction ${String(state.index + 1)}`}
                  onClick={() => {
                    update(
                      items.filter((_, index) => index !== state.index),
                      ids.filter((_, index) => index !== state.index),
                    );
                  }}
                >
                  <X aria-hidden />
                </Button>
              )}
            </div>
          );
        }}
      />
      {!ctx.readOnly && (
        <Button
          variant="ghost"
          size="28"
          className="self-start"
          onClick={() => {
            update([...items, ""]);
          }}
        >
          <Plus aria-hidden />
          Add instruction
        </Button>
      )}
    </div>
  );
}

function needsApproval(tool: ToolEntry): boolean {
  return tool.requires_confirmation === true || Boolean(tool.approval_type);
}

function toolKey(tool: ToolEntry): string {
  return tool.toolkit ?? tool.name;
}

function ToolsField({ name, ctx }: { name: string; ctx: FormContext }) {
  const attached = tools(ctx.config);
  const [adding, setAdding] = useState(false);
  const all = ctx.registry.byType("tool");
  const available = all.filter((entry) => !attached.some((tool) => toolKey(tool) === entry.name));
  const groups = [...new Set(attached.map(toolKey))];
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-2" aria-label="Attached tools">
        {groups.map((group) => {
          const index = attached.findIndex((tool) => toolKey(tool) === group);
          const members = attached.filter((tool) => toolKey(tool) === group);
          const first = attached[index];
          const approval = members.some(needsApproval);
          const entry = ctx.registry.find("tool", group);
          const path = `${name}[${String(index)}]`;
          return (
            <ToolCard
              key={group}
              name={first?.toolkit ?? first?.name ?? group}
              entry={entry}
              functions={first?.toolkit ? members.length : 0}
              approval={approval}
              lineLink={<LineLink path={path} ctx={ctx} />}
              onRemove={
                ctx.readOnly
                  ? undefined
                  : () => {
                      const next = attached.filter((tool) => toolKey(tool) !== group);
                      ctx.onChange((config) => withField(config, name, next.length ? next : undefined));
                    }
              }
            />
          );
        })}
      </ul>
      {!ctx.readOnly && (
        <>
          <Button
            variant="dashed-add"
            size="28"
            className="self-start"
            onClick={() => {
              setAdding(true);
            }}
          >
            <Plus aria-hidden />
            Add a tool
          </Button>
          <ToolPicker
            open={adding}
            onOpenChange={setAdding}
            instance={ctx.instance}
            available={available}
            offered={all.filter((entry) => entry.catalog)}
            onPick={(entry) => {
              if (!Array.isArray(entry.config_value)) return;
              const added = entry.config_value as ToolEntry[];
              ctx.onChange((config) => withField(config, name, [...tools(config), ...added]));
            }}
          />
        </>
      )}
    </div>
  );
}

function RefField({ name, info, ctx }: { name: string; info: FieldInfo; ctx: FormContext }) {
  const type = REF_TYPES[info.widget] ?? info.widget;
  const value = ctx.config[name];
  const current =
    info.widget === "schema"
      ? typeof value === "string"
        ? value
        : undefined
      : refName(value, REF_KEYS[info.widget] ?? "name");
  if (info.widget === "schema" && isRecord(value)) {
    return <p className="text-[12px] text-fg-muted">An inline JSON Schema; edit it under Advanced.</p>;
  }
  return (
    <RegistrySelect
      id={fieldId(name)}
      type={type}
      label={info.label}
      value={current}
      ctx={ctx}
      onChange={(picked) => {
        ctx.onChange((config) => withField(config, name, picked?.config_value ?? undefined));
      }}
    />
  );
}

function CodeOwnedField({ name, info, ctx }: { name: string; info: FieldInfo; ctx: FormContext }) {
  return (
    <FieldFrame name={name} info={info} ctx={ctx}>
      {(id) => (
        <div
          id={id}
          className="flex flex-wrap items-center gap-2 rounded-control border border-dashed border-border px-3 py-2 text-[12px] text-fg-secondary"
        >
          <span className="flex-1">Set in code in a way the form can't edit.</span>
          <Button
            variant="outline"
            size="28"
            onClick={() => {
              ctx.onEditInCode?.(name);
            }}
          >
            Edit in code
          </Button>
        </div>
      )}
    </FieldFrame>
  );
}

function FieldControl({ name, info, ctx }: { name: string; info: FieldInfo; ctx: FormContext }) {
  if (ctx.isCodeOwned?.(name)) return <CodeOwnedField name={name} info={info} ctx={ctx} />;
  return <EditableField name={name} info={info} ctx={ctx} />;
}

function EditableField({ name, info, ctx }: { name: string; info: FieldInfo; ctx: FormContext }) {
  const value = ctx.config[name];
  const set = (next: unknown) => {
    ctx.onChange((config) => withField(config, name, next));
  };
  const readOnly = ctx.readOnly ?? false;
  switch (info.widget) {
    case "switch": {
      const fallback = typeof info.default === "boolean" ? info.default : false;
      return (
        <FieldFrame name={name} info={info} ctx={ctx} inline>
          {() => (
            <Switch
              checked={typeof value === "boolean" ? value : fallback}
              disabled={readOnly}
              label={info.label}
              description={info.help}
              onCheckedChange={(checked) => {
                set(checked === fallback && info.default !== undefined ? undefined : checked);
              }}
            />
          )}
        </FieldFrame>
      );
    }
    case "number":
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {(id) => (
            <Input
              id={id}
              type="number"
              mono
              className="h-8 w-28"
              readOnly={readOnly}
              value={typeof value === "number" ? String(value) : ""}
              placeholder={typeof info.default === "number" ? String(info.default) : ""}
              onChange={(event) => {
                const raw = event.target.value;
                set(raw === "" ? undefined : Number(raw));
              }}
            />
          )}
        </FieldFrame>
      );
    case "textarea":
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {(id) => (
            <Textarea
              id={id}
              rows={3}
              readOnly={readOnly}
              value={typeof value === "string" ? value : ""}
              onChange={(event) => {
                set(event.target.value || undefined);
              }}
            />
          )}
        </FieldFrame>
      );
    case "select":
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {(id) => (
            <Select
              value={typeof value === "string" ? value : typeof info.default === "string" ? info.default : ""}
              disabled={readOnly}
              onValueChange={(next) => {
                set(next === info.default ? undefined : next);
              }}
            >
              <SelectTrigger id={id} className="h-8 w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(info.options ?? []).map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </FieldFrame>
      );
    case "model":
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {() => <ModelField name={name} ctx={ctx} />}
        </FieldFrame>
      );
    case "string_list":
      return <InstructionsField name={name} ctx={ctx} />;
    case "tools":
      return <ToolsField name={name} ctx={ctx} />;
    case "knowledge":
    case "schema":
    case "memory_manager":
    case "learning":
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {() => <RefField name={name} info={info} ctx={ctx} />}
        </FieldFrame>
      );
    case "json":
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {() =>
            readOnly ? (
              <pre className="rounded-control bg-inset p-2 font-mono text-[12px]">
                {JSON.stringify(value ?? null, null, 2)}
              </pre>
            ) : (
              <JsonEditor
                label={info.label}
                value={isRecord(value) ? value : undefined}
                onSave={(next) => {
                  set(Object.keys(next).length ? next : undefined);
                }}
              />
            )
          }
        </FieldFrame>
      );
    default:
      return (
        <FieldFrame name={name} info={info} ctx={ctx}>
          {(id) => (
            <Input
              id={id}
              mono={name === "id"}
              className="h-8"
              readOnly={readOnly || name === "id"}
              value={typeof value === "string" ? value : ""}
              onChange={(event) => {
                set(event.target.value || undefined);
              }}
            />
          )}
        </FieldFrame>
      );
  }
}

/** The raw config, as Agno Studio offers it: edits apply when saved here. */
export function RawConfigEditor({ ctx }: { ctx: FormContext }) {
  return (
    <JsonEditor
      label="Config (to_dict JSON)"
      value={ctx.config}
      onSave={(next) => {
        ctx.onChange(() => next);
      }}
      footer={
        <p className="text-[11.5px] text-fg-muted">
          Unknown keys are kept as they are, so settings from newer agno versions survive.
        </p>
      }
    />
  );
}

export function ConfigForm({
  sections,
  fields,
  ctx,
  custom = {},
  ariaLabel,
}: {
  sections: readonly Section[];
  fields: Record<string, FieldInfo>;
  ctx: FormContext;
  /** Sections rendered by the caller instead of field by field (the team's mode cards, its members). */
  custom?: Record<string, ReactNode>;
  ariaLabel: string;
}) {
  return (
    <Accordion aria-label={ariaLabel}>
      {sections.map((section) => {
        const shown = section.fields.filter((name) => {
          const info = fields[name];
          return info && (!info.legacy || ctx.config[name] !== undefined);
        });
        return (
          <AccordionSection
            key={section.id}
            id={`section-${section.id}`}
            title={section.label}
            summary={sectionSummary(section.id, ctx.config)}
            defaultOpen={OPEN_BY_DEFAULT.has(section.id)}
            contentClassName="flex flex-col gap-4"
          >
            {custom[section.id] ?? null}
            {!(section.id in custom) &&
              shown.map((name) => {
                const info = fields[name];
                return info ? <FieldControl key={name} name={name} info={info} ctx={ctx} /> : null;
              })}
            {section.id === "advanced" && !ctx.readOnly && <RawConfigEditor ctx={ctx} />}
          </AccordionSection>
        );
      })}
    </Accordion>
  );
}

export { FieldControl };
