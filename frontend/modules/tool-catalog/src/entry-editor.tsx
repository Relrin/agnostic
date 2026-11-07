// The sheet that adds or changes a catalog entry: level (and group or instance), then an MCP server (transport, URL,
// headers whose credentials are environment variable names, which tools to offer) or an Agno toolkit (its
// parameters, generated from the toolkit list).
import {
  describeError,
  directoryListGroupsOptions,
  toolCatalogCreateEntryMutation,
  toolCatalogListToolkitsOptions,
  toolCatalogUpdateEntryMutation,
  type EntryIn,
  type EntryOut,
  type ToolkitOut,
  type ToolkitParamOut,
} from "@agnostic/api";
import { STALE_TIME, useCan, useInstances, withQueryFn } from "@agnostic/core";
import {
  BRAND_GLYPHS,
  BRAND_OPTIONS,
  Badge,
  BrandIcon,
  Button,
  Callout,
  Checkbox,
  Combobox,
  Input,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Switch,
  ToolMark,
  toolBrand,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import {
  LEVELS,
  TRANSPORTS,
  formValue,
  isEnvRef,
  listText,
  paramValue,
  refreshCatalog,
  slugOf,
  textList,
  type Kind,
  type Level,
  type Transport,
} from "./catalog-api";

/** `format`: as stored (`null`: none); `undefined` for a new header (Authorization then gets `Bearer {}`). */
type Header = { name: string; value: string; secret: boolean; format?: string | null };

type State = {
  level: Level;
  group: string;
  instance: string;
  /** Organization and team entries: where they go (empty: every instance, for catalog managers). */
  instances: string[];
  /** Toolkit parameters stored as environment variables: they stay environment variables. */
  envParams: string[];
  displayName: string;
  /** A brand logo picked by hand; empty: the logo follows the toolkit, URL, command or name. */
  icon: string;
  slug: string;
  slugTouched: boolean;
  description: string;
  kind: Kind;
  transport: Transport;
  url: string;
  headers: Header[];
  command: string;
  args: string;
  include: string;
  exclude: string;
  prefix: string;
  toolkit: string;
  params: Record<string, string | boolean>;
};

function initial(entry: EntryOut | undefined, level: Level): State {
  const config = entry?.config ?? {};
  const headers = Object.entries((config.headers as Record<string, unknown> | undefined) ?? {}).map(
    ([name, value]): Header =>
      isEnvRef(value)
        ? { name, value: value.env, secret: true, format: value.format ?? null }
        : { name, value: String(value), secret: false },
  );
  const params = (config.params as Record<string, unknown> | undefined) ?? {};
  return {
    level: entry?.level ?? level,
    group: entry?.owner_group_id ?? "",
    instance: entry?.instance_ids[0] ?? "",
    instances: entry?.instance_ids ?? [],
    envParams: Object.entries(params)
      .filter(([, value]) => isEnvRef(value))
      .map(([key]) => key),
    displayName: entry?.display_name ?? "",
    icon: entry?.icon ?? "",
    slug: entry?.slug ?? "",
    slugTouched: Boolean(entry),
    description: entry?.description ?? "",
    kind: entry?.kind ?? "mcp",
    transport: entry?.transport ?? "streamable-http",
    url: typeof config.url === "string" ? config.url : "",
    headers: headers.length ? headers : [{ name: "Authorization", value: "", secret: true }],
    command: typeof config.command === "string" ? config.command : "npx",
    args: listText(config.args),
    include: listText(config.include_tools),
    exclude: listText(config.exclude_tools),
    prefix: typeof config.tool_name_prefix === "string" ? config.tool_name_prefix : "",
    toolkit: entry?.toolkit_key ?? "",
    params: Object.fromEntries(
      Object.entries(params)
        .map(([key, value]) => [key, formValue(value)] as const)
        .filter((pair): pair is readonly [string, string | boolean] => pair[1] !== undefined),
    ),
  };
}

/** The stored settings the form has no control for (timeout, a stdio server's variables…): kept as they were. */
const FORM_KEYS = new Set([
  "transport",
  "url",
  "headers",
  "command",
  "args",
  "include_tools",
  "exclude_tools",
]);

/** The stored settings the form has no control for (timeout, a stdio server's variables…): kept as they were. */
function untouched(entry: EntryOut | undefined): Record<string, unknown> {
  if (entry?.kind !== "mcp") return {};
  return Object.fromEntries(Object.entries(entry.config).filter(([key]) => !FORM_KEYS.has(key)));
}

function headerValue(header: Header): unknown {
  const value = header.value.trim();
  if (!header.secret) return value;
  const format =
    header.format === undefined
      ? header.name.trim().toLowerCase() === "authorization"
        ? "Bearer {}"
        : null
      : header.format;
  return format ? { env: value, format } : { env: value };
}

function mcpConfig(state: State): Record<string, unknown> {
  const tools = { include_tools: textList(state.include), exclude_tools: textList(state.exclude) };
  const prefix = state.prefix.trim() ? { tool_name_prefix: state.prefix.trim() } : {};
  if (state.transport === "stdio") {
    return {
      command: state.command.trim(),
      args: state.args.trim() ? state.args.trim().split(/\s+/) : [],
      ...tools,
      ...prefix,
    };
  }
  const headers = Object.fromEntries(
    state.headers
      .filter((header) => header.name.trim() && header.value.trim())
      .map((header) => [header.name.trim(), headerValue(header)]),
  );
  return { url: state.url.trim(), headers, ...tools, ...prefix };
}

function toolkitConfig(state: State, toolkit: ToolkitOut | undefined): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const param of toolkit?.params ?? []) {
    const value = paramValue(param, state.params[param.name], state.envParams.includes(param.name));
    if (value !== undefined) params[param.name] = value;
  }
  return { params };
}

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[12.5px] font-medium text-fg">
        {label}
      </label>
      {children(id)}
      {hint && <p className="text-[11.5px] text-fg-muted">{hint}</p>}
    </div>
  );
}

export function EntryEditor({
  open,
  onOpenChange,
  entry,
  defaultLevel = "org",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Change this entry; add a new one without it. */
  entry?: EntryOut | undefined;
  defaultLevel?: Level;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[min(640px,100%)] overflow-y-auto">
        {open && (
          <EditorForm
            key={entry?.id ?? "new"}
            entry={entry}
            defaultLevel={defaultLevel}
            onDone={() => {
              onOpenChange(false);
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function EditorForm({
  entry,
  defaultLevel,
  onDone,
}: {
  entry: EntryOut | undefined;
  defaultLevel: Level;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [state, setState] = useState<State>(() => initial(entry, defaultLevel));
  const set = (patch: Partial<State>) => {
    setState((current) => ({ ...current, ...patch }));
  };
  const canLocal = useCan("tool_catalog:local").allowed === true;
  const canManage = useCan("tool_catalog:write").allowed === true;
  const instances = useInstances();
  const groups = useQuery({ ...withQueryFn(directoryListGroupsOptions()), staleTime: STALE_TIME.list });
  const toolkits = useQuery({
    ...withQueryFn(toolCatalogListToolkitsOptions()),
    staleTime: STALE_TIME.config,
  });
  const toolkit = toolkits.data?.toolkits.find((item) => item.key === state.toolkit);
  const editing = Boolean(entry);

  const create = useMutation({
    ...toolCatalogCreateEntryMutation(),
    onSuccess: async () => {
      await refreshCatalog(client);
      onDone();
    },
  });
  const update = useMutation({
    ...toolCatalogUpdateEntryMutation(),
    onSuccess: async () => {
      await refreshCatalog(client);
      onDone();
    },
  });
  const error = create.error ?? update.error;
  const pending = create.isPending || update.isPending;

  const submit = () => {
    const config =
      state.kind === "mcp" ? { ...untouched(entry), ...mcpConfig(state) } : toolkitConfig(state, toolkit);
    const instanceIds = state.level === "custom" ? (state.instance ? [state.instance] : []) : state.instances;
    if (entry) {
      update.mutate({
        path: { entry_id: entry.id },
        body: {
          version: entry.version,
          display_name: state.displayName,
          description: state.description,
          icon: state.icon || null,
          ...(entry.kind === "mcp" ? { transport: state.transport } : {}),
          config,
          instance_ids: instanceIds,
        },
      });
      return;
    }
    const body: EntryIn = {
      slug: state.slug || slugOf(state.displayName),
      level: state.level,
      display_name: state.displayName,
      description: state.description,
      icon: state.icon || null,
      kind: state.kind,
      owner_group_id: state.level === "team" ? state.group || null : null,
      transport: state.kind === "mcp" ? state.transport : null,
      toolkit_key: state.kind === "toolkit" ? state.toolkit : null,
      config,
      instance_ids: instanceIds,
    };
    create.mutate({ body });
  };

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex flex-col gap-1 pr-8">
        <SheetTitle className="text-[16px] font-semibold">
          {editing ? `Change ${entry?.display_name ?? ""}` : "Add to the tool catalog"}
        </SheetTitle>
        <SheetDescription className="text-[12.5px] text-fg-secondary">
          Runtimes pull the catalog and register each entry, so builders find it as a tool block in Studio.
          Credentials stay on the runtime: give the name of the environment variable that holds them.
        </SheetDescription>
      </div>

      {!editing && (
        <Row label="Level" hint={LEVELS.find((level) => level.value === state.level)?.hint}>
          {() => (
            <SegmentedControl
              label="Level"
              value={state.level}
              onValueChange={(level) => {
                set({ level });
              }}
              options={LEVELS.map((level) => ({ value: level.value, label: level.label }))}
            />
          )}
        </Row>
      )}

      {!editing && state.level === "team" && (
        <Row label="Team" hint="Its members see the entry; its owners change it.">
          {(id) => (
            <Select
              value={state.group}
              onValueChange={(group) => {
                set({ group });
              }}
            >
              <SelectTrigger id={id} className="h-8">
                <SelectValue placeholder="Pick a group" />
              </SelectTrigger>
              <SelectContent>
                {(groups.data ?? []).map((group) => (
                  <SelectItem key={group.id} value={group.id}>
                    {group.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Row>
      )}

      {state.level !== "custom" && (
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1 text-[12.5px] font-medium text-fg">Instances</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {(instances.data ?? []).map((instance) => (
              <Checkbox
                key={instance.id}
                label={instance.display_name}
                checked={state.instances.includes(instance.id)}
                onCheckedChange={(checked) => {
                  set({
                    instances:
                      checked === true
                        ? [...state.instances, instance.id]
                        : state.instances.filter((other) => other !== instance.id),
                  });
                }}
              />
            ))}
          </div>
          <p className="text-[11.5px] text-fg-muted">
            {state.instances.length
              ? "Only these instances' runtimes get it."
              : canManage
                ? "None picked: every instance's runtime gets it."
                : "Pick the instances you build on."}
          </p>
        </fieldset>
      )}

      {state.level === "custom" && (
        <Row label="Instance" hint="A custom entry is made for the instance its component is on.">
          {(id) => (
            <Select
              value={state.instance}
              onValueChange={(instance) => {
                set({ instance });
              }}
            >
              <SelectTrigger id={id} className="h-8">
                <SelectValue placeholder="Pick an instance" />
              </SelectTrigger>
              <SelectContent>
                {(instances.data ?? []).map((instance) => (
                  <SelectItem key={instance.id} value={instance.id}>
                    {instance.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Row>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Row label="Name">
          {(id) => (
            <Input
              id={id}
              value={state.displayName}
              placeholder="Linear"
              onChange={(event) => {
                const displayName = event.target.value;
                set(state.slugTouched ? { displayName } : { displayName, slug: slugOf(displayName) });
              }}
            />
          )}
        </Row>
        <Row
          label="Short name"
          hint={
            editing ? "Fixed: runtimes know the tool by it." : "The registry name adds the level in front."
          }
        >
          {(id) => (
            <Input
              id={id}
              className="font-mono"
              disabled={editing}
              value={editing ? (entry?.registry_name ?? "") : state.slug}
              onChange={(event) => {
                set({ slug: event.target.value, slugTouched: true });
              }}
            />
          )}
        </Row>
      </div>
      <Row label="Description">
        {(id) => (
          <Input
            id={id}
            value={state.description}
            placeholder="What builders use it for"
            onChange={(event) => {
              set({ description: event.target.value });
            }}
          />
        )}
      </Row>

      {!editing && (
        <Row label="Kind">
          {() => (
            <SegmentedControl
              label="Kind"
              value={state.kind}
              onValueChange={(kind) => {
                set({ kind });
              }}
              options={[
                { value: "mcp", label: "MCP server" },
                { value: "toolkit", label: "Agno toolkit" },
              ]}
            />
          )}
        </Row>
      )}

      {state.kind === "mcp" ? (
        <McpFields state={state} set={set} canLocal={canLocal} />
      ) : (
        <ToolkitFields
          state={state}
          set={set}
          toolkits={toolkits.data?.toolkits ?? []}
          toolkit={toolkit}
          editing={editing}
          canLocal={canLocal}
        />
      )}

      <IconField state={state} set={set} />

      {error && (
        <Callout tone="danger" title="Not saved">
          {describeError(error).reason}
        </Callout>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={pending || !state.displayName.trim()}>
          {pending ? "Saving…" : editing ? "Save changes" : "Add to the catalog"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

const AUTOMATIC = "__automatic__";

/** The logo builders see on the tool: picked here, or found from the toolkit, the URL, the command or the name. */
function IconField({ state, set }: { state: State; set: (patch: Partial<State>) => void }) {
  const detected = toolBrand({
    kind: state.kind,
    toolkitKey: state.kind === "toolkit" ? state.toolkit : undefined,
    hints:
      state.kind === "mcp"
        ? [state.displayName, state.transport === "stdio" ? `${state.command} ${state.args}` : state.url]
        : [state.displayName],
  });
  const mark = (icon: string) => (
    <ToolMark
      kind={state.kind}
      icon={icon}
      toolkitKey={state.kind === "toolkit" ? state.toolkit : undefined}
      hints={[]}
      className="size-4 text-fg"
    />
  );
  return (
    <Row
      label="Icon"
      hint={
        state.icon
          ? "Shown on the tool in Studio's editors and the workflow builder."
          : detected
            ? `Found from the ${state.kind === "toolkit" ? "toolkit" : "name, URL or command"}: ${BRAND_GLYPHS[detected].title}.`
            : "Nothing names a known service: a generic icon shows. Pick a logo if the tool has one."
      }
    >
      {(id) => (
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="grid size-[34px] shrink-0 place-items-center rounded-button border border-border-input bg-surface-hover"
          >
            {mark(state.icon || (detected ?? ""))}
          </span>
          <Combobox
            id={id}
            aria-label="Icon"
            value={state.icon || AUTOMATIC}
            searchPlaceholder="Search logos…"
            onValueChange={(value) => {
              set({ icon: value === AUTOMATIC ? "" : value });
            }}
            options={[
              {
                value: AUTOMATIC,
                label: "Automatic",
                hint: detected ? BRAND_GLYPHS[detected].title : "generic",
              },
              ...BRAND_OPTIONS.filter((option) => option.id !== "mcp").map((option) => ({
                value: option.id,
                label: option.title,
                keywords: [option.id],
                icon: <BrandIcon brand={option.id} />,
              })),
            ]}
          />
        </div>
      )}
    </Row>
  );
}

function McpFields({
  state,
  set,
  canLocal,
}: {
  state: State;
  set: (patch: Partial<State>) => void;
  canLocal: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-tile border border-border-subtle p-4">
      <Row label="Transport" hint={TRANSPORTS.find((item) => item.value === state.transport)?.hint}>
        {() => (
          <SegmentedControl
            label="Transport"
            value={state.transport}
            onValueChange={(transport) => {
              set({ transport });
            }}
            options={TRANSPORTS.map((item) => ({
              value: item.value,
              label: item.label,
              disabled: item.value === "stdio" && !canLocal,
            }))}
          />
        )}
      </Row>
      {state.transport === "stdio" ? (
        <div className="grid grid-cols-[140px_1fr] gap-3">
          <Row label="Command" hint="Allowed per runtime (AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS).">
            {(id) => (
              <Input
                id={id}
                className="font-mono"
                value={state.command}
                onChange={(event) => {
                  set({ command: event.target.value });
                }}
              />
            )}
          </Row>
          <Row label="Arguments">
            {(id) => (
              <Input
                id={id}
                className="font-mono"
                value={state.args}
                placeholder="-y @modelcontextprotocol/server-filesystem /data"
                onChange={(event) => {
                  set({ args: event.target.value });
                }}
              />
            )}
          </Row>
        </div>
      ) : (
        <>
          <Row label="Server URL">
            {(id) => (
              <Input
                id={id}
                className="font-mono"
                value={state.url}
                placeholder="https://mcp.example.com/mcp"
                onChange={(event) => {
                  set({ url: event.target.value });
                }}
              />
            )}
          </Row>
          <div className="flex flex-col gap-2">
            <p className="text-[12.5px] font-medium text-fg">Headers</p>
            {state.headers.map((header, index) => (
              <div key={index} className="grid grid-cols-[1fr_1fr_auto_auto] items-center gap-2">
                <Input
                  aria-label={`Header ${String(index + 1)} name`}
                  className="font-mono"
                  value={header.name}
                  placeholder="Authorization"
                  onChange={(event) => {
                    const headers = [...state.headers];
                    headers[index] = { ...header, name: event.target.value };
                    set({ headers });
                  }}
                />
                <Input
                  aria-label={`Header ${String(index + 1)} ${header.secret ? "environment variable" : "value"}`}
                  className="font-mono"
                  value={header.value}
                  placeholder={header.secret ? "LINEAR_TOKEN" : "value"}
                  onChange={(event) => {
                    const headers = [...state.headers];
                    headers[index] = {
                      ...header,
                      value: header.secret ? event.target.value.toUpperCase() : event.target.value,
                    };
                    set({ headers });
                  }}
                />
                <Switch
                  hideLabel
                  label={`Header ${String(index + 1)} comes from an environment variable`}
                  checked={header.secret}
                  onCheckedChange={(secret) => {
                    const headers = [...state.headers];
                    headers[index] = { ...header, secret };
                    set({ headers });
                  }}
                />
                <Button
                  type="button"
                  variant="icon"
                  size="28"
                  aria-label={`Remove header ${String(index + 1)}`}
                  onClick={() => {
                    set({ headers: state.headers.filter((_, other) => other !== index) });
                  }}
                >
                  <X aria-hidden />
                </Button>
              </div>
            ))}
            <p className="text-[11.5px] text-fg-muted">
              Switched on: the value is the name of an environment variable on the runtime. Authorization
              headers are sent as <code className="font-mono">Bearer &lt;value&gt;</code>.
            </p>
            <Button
              type="button"
              variant="dashed-add"
              size="28"
              className="self-start"
              onClick={() => {
                set({ headers: [...state.headers, { name: "", value: "", secret: true }] });
              }}
            >
              <Plus aria-hidden />
              Add a header
            </Button>
          </div>
        </>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Row label="Offer only these tools" hint="Comma-separated; empty offers every tool.">
          {(id) => (
            <Input
              id={id}
              className="font-mono"
              value={state.include}
              onChange={(event) => {
                set({ include: event.target.value });
              }}
            />
          )}
        </Row>
        <Row label="Hide these tools">
          {(id) => (
            <Input
              id={id}
              className="font-mono"
              value={state.exclude}
              onChange={(event) => {
                set({ exclude: event.target.value });
              }}
            />
          )}
        </Row>
      </div>
      <Row
        label="Tool name prefix"
        hint="Defaults to the registry name, so two servers' tools never collide."
      >
        {(id) => (
          <Input
            id={id}
            className="font-mono"
            value={state.prefix}
            placeholder="org_linear_"
            onChange={(event) => {
              set({ prefix: event.target.value });
            }}
          />
        )}
      </Row>
    </div>
  );
}

function ToolkitFields({
  state,
  set,
  toolkits,
  toolkit,
  editing,
  canLocal,
}: {
  state: State;
  set: (patch: Partial<State>) => void;
  toolkits: ToolkitOut[];
  toolkit: ToolkitOut | undefined;
  editing: boolean;
  canLocal: boolean;
}) {
  const params = [...(toolkit?.params ?? [])].sort(
    (a, b) => Number(b.required) - Number(a.required) || a.name.localeCompare(b.name),
  );
  return (
    <div className="flex flex-col gap-4 rounded-tile border border-border-subtle p-4">
      <Row
        label="Toolkit"
        hint={toolkit?.extra ? `The runtime needs ${toolkit.extra} installed.` : undefined}
      >
        {() => (
          <Combobox
            aria-label="Toolkit"
            value={state.toolkit || undefined}
            disabled={editing}
            placeholder="Pick a toolkit"
            searchPlaceholder="Search toolkits…"
            emptyText="No toolkit matches."
            options={toolkits
              .filter((item) => !item.local || canLocal)
              .map((item) => ({ value: item.key, label: item.label, hint: item.category }))}
            onValueChange={(key) => {
              set({ toolkit: key, params: {} });
            }}
          />
        )}
      </Row>
      {toolkit?.local && (
        <Callout tone="warning" title="Runs commands on the runtime">
          Runtimes build it only when they allow it (AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL=true).
        </Callout>
      )}
      {params.map((param) => (
        <ParamField
          key={param.name}
          param={param}
          value={state.params[param.name]}
          onChange={(value) => {
            set({ params: { ...state.params, [param.name]: value } });
          }}
        />
      ))}
      {toolkit && params.length === 0 && (
        <p className="text-[12.5px] text-fg-muted">{toolkit.label} has no settings.</p>
      )}
    </div>
  );
}

function ParamField({
  param,
  value,
  onChange,
}: {
  param: ToolkitParamOut;
  value: string | boolean | undefined;
  onChange: (value: string | boolean) => void;
}) {
  const label = (
    <span className="flex items-center gap-1.5">
      <code className="font-mono text-[12px]">{param.name}</code>
      {param.required && <Badge tone="warning">required</Badge>}
      {param.secret && <Badge tone="info">environment variable</Badge>}
    </span>
  );
  if (param.type === "bool" && !param.secret) {
    return (
      <Switch
        label={label}
        description={param.description || undefined}
        checked={typeof value === "boolean" ? value : param.default === true}
        onCheckedChange={onChange}
      />
    );
  }
  return (
    <div className="flex flex-col gap-1 text-[12.5px]">
      {label}
      {param.description && <span className="text-fg-muted">{param.description}</span>}
      <Input
        aria-label={param.name}
        className="font-mono"
        placeholder={
          param.secret ? "ENV_VAR_NAME" : param.choices.length ? param.choices.map(String).join(" | ") : ""
        }
        value={typeof value === "string" ? value : ""}
        onChange={(event) => {
          onChange(param.secret ? event.target.value.toUpperCase() : event.target.value);
        }}
      />
    </div>
  );
}
