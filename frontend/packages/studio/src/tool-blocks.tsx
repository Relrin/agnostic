// Tools as blocks: a card per attached tool (where it comes from, how the runtime is doing with it) and a picker that
// offers the tool catalog by level (organization, your teams, yours), every Agno toolkit to configure yourself, and
// the tools the runtime's own code registered.
import {
  describeError,
  toolCatalogCreateEntryMutation,
  toolCatalogListToolkitsOptions,
  type RegistryEntryOut,
  type ToolkitOut,
  type ToolkitParamOut,
} from "@agnostic/api";
import { STALE_TIME, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Switch,
  cn,
  type BadgeProps,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Blocks, Code2, Plug, Search, Wrench, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

type Catalog = NonNullable<RegistryEntryOut["catalog"]>;

const LEVEL_TONE: Record<Catalog["level"], NonNullable<BadgeProps["tone"]>> = {
  org: "success",
  team: "info",
  custom: "outline",
};

const STATE_TEXT: Record<string, { text: string; tone: NonNullable<BadgeProps["tone"]> }> = {
  connected: { text: "connected", tone: "success" },
  pending: { text: "connecting", tone: "warning" },
  not_on_instance: { text: "not on this instance yet", tone: "warning" },
  failed: { text: "not connected", tone: "danger" },
  missing_env: { text: "missing credential", tone: "danger" },
  stdio_disabled: { text: "not allowed here", tone: "danger" },
  conflict: { text: "name taken", tone: "danger" },
};

const CATEGORY_LABEL: Record<string, string> = {
  search: "Search",
  web: "Web",
  social: "Messaging",
  data: "Data",
  productivity: "Work tools",
  media: "Media",
  local: "On the runtime",
  other: "Other",
};

/** The icon of a tool: an MCP server, an Agno toolkit, or a tool from the runtime's code. */
export function ToolIcon({
  catalog,
  className,
}: {
  catalog: Catalog | null | undefined;
  className?: string;
}) {
  const Icon = catalog?.kind === "mcp" ? Plug : catalog?.kind === "toolkit" ? Wrench : Code2;
  return <Icon aria-hidden className={cn("size-3.5 shrink-0", className)} />;
}

/** "Organization", "Team · Data", "Custom": where a catalog tool comes from. */
export function LevelBadge({ catalog }: { catalog: Catalog }) {
  return <Badge tone={LEVEL_TONE[catalog.level]}>{catalog.level_label}</Badge>;
}

export function StateBadge({ catalog }: { catalog: Catalog }) {
  if (catalog.state === "connected") return null;
  const state = STATE_TEXT[catalog.state] ?? { text: catalog.state, tone: "muted" as const };
  return (
    <Badge tone={state.tone} title={catalog.detail ?? undefined}>
      {state.text}
    </Badge>
  );
}

function kindLabel(catalog: Catalog | null | undefined): string {
  if (!catalog) return "Registered in code";
  return catalog.kind === "mcp"
    ? `MCP server${catalog.transport ? ` · ${catalog.transport}` : ""}`
    : "Agno toolkit";
}

/** One attached tool as a block: icon, name, where it comes from, approval and runtime state, and a remove button. */
export function ToolCard({
  name,
  entry,
  functions,
  approval,
  lineLink,
  onRemove,
}: {
  name: string;
  entry: RegistryEntryOut | undefined;
  functions: number;
  approval: boolean;
  lineLink?: ReactNode;
  onRemove?: (() => void) | undefined;
}) {
  const catalog = entry?.catalog;
  return (
    <li
      className={cn(
        "flex max-w-[320px] min-w-[220px] flex-1 items-start gap-2.5 rounded-control border bg-surface px-3 py-2",
        approval ? "border-warning/45" : "border-border-input",
        !entry && "border-danger/45",
      )}
    >
      <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-[6px] bg-surface-hover text-fg-secondary">
        <ToolIcon catalog={catalog} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-medium text-fg">{catalog?.display_name ?? name}</span>
          {lineLink}
        </div>
        {catalog && <code className="truncate font-mono text-[11px] text-fg-muted">{name}</code>}
        <div className="flex flex-wrap items-center gap-1">
          {catalog && <LevelBadge catalog={catalog} />}
          <span className="text-[11px] text-fg-muted">
            {kindLabel(catalog)}
            {functions > 0 && ` · ${String(functions)} tool${functions === 1 ? "" : "s"}`}
          </span>
          {approval && <Badge tone="warning">needs approval</Badge>}
          {catalog && <StateBadge catalog={catalog} />}
          {!entry && <Badge tone="danger">not registered</Badge>}
        </div>
      </div>
      {onRemove && (
        <Button variant="icon" size="28" className="size-6" aria-label={`Remove ${name}`} onClick={onRemove}>
          <X aria-hidden />
        </Button>
      )}
    </li>
  );
}

type Section = { id: string; title: string; hint: string; entries: RegistryEntryOut[] };

function sections(available: RegistryEntryOut[]): Section[] {
  const org = available.filter((entry) => entry.catalog?.level === "org");
  const custom = available.filter((entry) => entry.catalog?.level === "custom");
  const code = available.filter((entry) => !entry.catalog);
  const teams = new Map<string, RegistryEntryOut[]>();
  for (const entry of available) {
    if (entry.catalog?.level !== "team") continue;
    teams.set(entry.catalog.level_label, [...(teams.get(entry.catalog.level_label) ?? []), entry]);
  }
  return [
    { id: "org", title: "Organization", hint: "Approved for everyone", entries: org },
    ...[...teams].map(([label, entries]) => ({
      id: `team:${label}`,
      title: label,
      hint: "Set up by your team",
      entries,
    })),
    { id: "custom", title: "Custom", hint: "Set up by builders on this instance", entries: custom },
    { id: "code", title: "Runtime registry", hint: "Registered in the runtime's code", entries: code },
  ].filter((section) => section.entries.length > 0);
}

function matches(entry: RegistryEntryOut, needle: string): boolean {
  if (!needle) return true;
  const text = `${entry.name} ${entry.catalog?.display_name ?? ""} ${entry.description ?? ""}`.toLowerCase();
  return text.includes(needle);
}

/** A tile in the picker. */
function Tile({
  icon,
  title,
  subtitle,
  badges,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  badges?: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex cursor-pointer items-start gap-2.5 rounded-control border border-border-input bg-surface px-3 py-2.5 text-left hover:border-border-strong hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-[6px] bg-surface-hover text-fg-secondary">
        {icon}
      </span>
      <span className="flex min-w-0 flex-col gap-1">
        <span className="truncate text-[13px] font-medium text-fg">{title}</span>
        <span className="line-clamp-2 text-[11.5px] text-fg-muted">{subtitle}</span>
        {badges && <span className="flex flex-wrap gap-1">{badges}</span>}
      </span>
    </button>
  );
}

/** The dialog that adds a tool: catalog sections, every Agno toolkit to configure, and the runtime's own tools. */
export function ToolPicker({
  open,
  onOpenChange,
  instance,
  available,
  offered,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The instance the component is on: custom toolkits are set up for it. */
  instance: string | undefined;
  /** Registry tools not attached yet. */
  available: RegistryEntryOut[];
  /** Every catalog tool on the instance (attached or not), for the "a version is already offered" hints. */
  offered: RegistryEntryOut[];
  onPick: (entry: RegistryEntryOut) => void;
}) {
  const [query, setQuery] = useState("");
  const [configuring, setConfiguring] = useState<ToolkitOut | undefined>();
  const needle = query.trim().toLowerCase();
  const toolkits = useQuery({
    ...withQueryFn(toolCatalogListToolkitsOptions({ query: instance ? { instance } : {} })),
    staleTime: STALE_TIME.config,
    enabled: open && Boolean(instance),
  });
  const grouped = sections(available.filter((entry) => matches(entry, needle)));
  const byToolkit = useMemo(() => {
    const found = new Map<string, RegistryEntryOut>();
    for (const entry of offered) {
      const key = entry.catalog?.toolkit_key;
      if (key && entry.catalog?.level !== "custom" && !found.has(key)) found.set(key, entry);
    }
    return found;
  }, [offered]);
  const rawToolkits = (toolkits.data?.toolkits ?? []).filter(
    (toolkit) =>
      !needle || `${toolkit.label} ${toolkit.key} ${toolkit.description}`.toLowerCase().includes(needle),
  );
  const categories = [...new Set(rawToolkits.map((toolkit) => toolkit.category))];

  const close = (next: boolean) => {
    if (!next) {
      setConfiguring(undefined);
      setQuery("");
    }
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>{configuring ? `Set up ${configuring.label}` : "Add a tool"}</DialogTitle>
          <DialogDescription>
            {configuring
              ? "A custom tool for this instance. Credentials are the names of environment variables on the runtime."
              : "Tools your organization and teams approved, every Agno toolkit, and the runtime's own tools."}
          </DialogDescription>
        </DialogHeader>
        {configuring && instance ? (
          <ConfigureToolkit
            instance={instance}
            toolkit={configuring}
            existing={byToolkit.get(configuring.key)}
            onBack={() => {
              setConfiguring(undefined);
            }}
            onDone={() => {
              close(false);
            }}
          />
        ) : (
          <div className="flex min-h-0 flex-col gap-4">
            <div className="relative flex items-center">
              <Search aria-hidden className="pointer-events-none absolute left-2.5 size-3.5 text-fg-muted" />
              <Input
                aria-label="Search tools"
                placeholder="Search tools…"
                className="pl-8"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                }}
              />
            </div>
            <div className="-mr-2 flex max-h-[60vh] flex-col gap-5 overflow-y-auto pr-2">
              {grouped.map((section) => (
                <section key={section.id} aria-label={section.title} className="flex flex-col gap-2">
                  <h3 className="flex items-baseline gap-2 text-[12px] font-semibold text-fg">
                    {section.title}
                    <span className="font-normal text-fg-muted">{section.hint}</span>
                  </h3>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {section.entries.map((entry) => (
                      <Tile
                        key={entry.name}
                        icon={<ToolIcon catalog={entry.catalog} />}
                        title={entry.catalog?.display_name ?? entry.name}
                        subtitle={entry.description ?? kindLabel(entry.catalog)}
                        disabled={!entry.studio_available}
                        badges={
                          <>
                            {entry.catalog && <LevelBadge catalog={entry.catalog} />}
                            {entry.catalog && <StateBadge catalog={entry.catalog} />}
                            {entry.requires_approval && <Badge tone="warning">needs approval</Badge>}
                          </>
                        }
                        onClick={() => {
                          onPick(entry);
                          close(false);
                        }}
                      />
                    ))}
                  </div>
                </section>
              ))}
              {instance && (
                <section aria-label="Agno toolkits" className="flex flex-col gap-2">
                  <h3 className="flex items-baseline gap-2 text-[12px] font-semibold text-fg">
                    Agno toolkits
                    <span className="font-normal text-fg-muted">Configure one yourself</span>
                  </h3>
                  {toolkits.isPending && <p className="text-[12px] text-fg-muted">Loading toolkits…</p>}
                  {categories.map((category) => (
                    <div key={category} className="flex flex-col gap-1.5">
                      <p className="text-[11px] font-medium tracking-[0.04em] text-fg-muted uppercase">
                        {CATEGORY_LABEL[category] ?? category}
                      </p>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                        {rawToolkits
                          .filter((toolkit) => toolkit.category === category)
                          .map((toolkit) => {
                            const existing = byToolkit.get(toolkit.key);
                            return (
                              <Tile
                                key={toolkit.key}
                                icon={<Blocks aria-hidden className="size-3.5" />}
                                title={toolkit.label}
                                subtitle={toolkit.description || toolkit.key}
                                badges={
                                  <>
                                    {existing?.catalog && (
                                      <Badge tone={LEVEL_TONE[existing.catalog.level]}>
                                        {existing.catalog.level_label} version available
                                      </Badge>
                                    )}
                                    {toolkit.importable === false && (
                                      <Badge tone="muted">not installed</Badge>
                                    )}
                                    {toolkit.local && <Badge tone="warning">runs commands</Badge>}
                                  </>
                                }
                                onClick={() => {
                                  setConfiguring(toolkit);
                                }}
                              />
                            );
                          })}
                      </div>
                    </div>
                  ))}
                </section>
              )}
              {grouped.length === 0 && rawToolkits.length === 0 && !toolkits.isPending && (
                <p className="text-[12.5px] text-fg-muted">No tool matches “{query}”.</p>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function slugOf(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .replace(/^[^a-z]+/, "")
      .slice(0, 40) || "tool"
  );
}

type Values = Record<string, string | boolean>;

function paramValue(param: ToolkitParamOut, raw: string | boolean | undefined): unknown {
  if (raw === undefined || raw === "") return undefined;
  if (param.secret) return { env: String(raw) };
  switch (param.type) {
    case "bool":
      return Boolean(raw);
    case "int":
      return Number.parseInt(String(raw), 10);
    case "float":
      return Number.parseFloat(String(raw));
    case "list":
    case "dict":
    case "json":
      try {
        return JSON.parse(String(raw)) as unknown;
      } catch {
        return String(raw);
      }
    default:
      return raw;
  }
}

/** The parameter form of a raw Agno toolkit, saved as a custom catalog entry for this instance. */
function ConfigureToolkit({
  instance,
  toolkit,
  existing,
  onBack,
  onDone,
}: {
  instance: string;
  toolkit: ToolkitOut;
  existing: RegistryEntryOut | undefined;
  onBack: () => void;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(toolkit.label);
  const [values, setValues] = useState<Values>({});
  const [saved, setSaved] = useState<string | undefined>();
  const create = useMutation({
    ...toolCatalogCreateEntryMutation(),
    onSuccess: async (entry) => {
      setSaved(entry.registry_name);
      await client.invalidateQueries({ queryKey: [{ _id: "studioRegistry" }] });
    },
  });
  const params = [...toolkit.params].sort(
    (a, b) => Number(b.required) - Number(a.required) || a.name.localeCompare(b.name),
  );
  const set = (key: string, value: string | boolean) => {
    setValues((current) => ({ ...current, [key]: value }));
  };

  if (saved) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-fg">
          <code className="font-mono">{saved}</code> is set up. It appears in this picker as soon as{" "}
          {instance}
          pulls the tool catalog, usually within a minute.
        </p>
        <Button className="self-start" onClick={onDone}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <form
      className="flex min-h-0 flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        const config: Record<string, unknown> = {};
        for (const param of toolkit.params) {
          const value = paramValue(param, values[param.name]);
          if (value !== undefined) config[param.name] = value;
        }
        create.mutate({
          body: {
            slug: slugOf(name),
            level: "custom",
            display_name: name,
            kind: "toolkit",
            toolkit_key: toolkit.key,
            config: { params: config },
            instance_ids: [instance],
          },
        });
      }}
    >
      {existing?.catalog && (
        <p className="rounded-control border border-info/30 bg-[var(--info-tint)] px-3 py-2 text-[12.5px] text-fg">
          {existing.catalog.level_label} already offers <strong>{existing.catalog.display_name}</strong>. Pick
          it instead unless you need your own settings.
        </p>
      )}
      <div className="flex flex-col gap-1 text-[12.5px] font-medium">
        <span>Name</span>
        <Input
          aria-label="Name"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </div>
      <div className="-mr-2 flex max-h-[45vh] flex-col gap-2.5 overflow-y-auto pr-2">
        {params.length === 0 && (
          <p className="text-[12.5px] text-fg-muted">{toolkit.label} has no settings.</p>
        )}
        {params.map((param) => (
          <ParamControl key={param.name} param={param} value={values[param.name]} onChange={set} />
        ))}
      </div>
      {create.error && <p className="text-[12.5px] text-danger">{describeError(create.error).reason}</p>}
      <div className="flex items-center gap-2">
        <Button type="button" variant="ghost" onClick={onBack}>
          <ArrowLeft aria-hidden />
          Back
        </Button>
        <Button type="submit" disabled={create.isPending || !name.trim()}>
          {create.isPending ? "Setting up…" : "Set up for this instance"}
        </Button>
      </div>
    </form>
  );
}

function ParamControl({
  param,
  value,
  onChange,
}: {
  param: ToolkitParamOut;
  value: string | boolean | undefined;
  onChange: (key: string, value: string | boolean) => void;
}) {
  const label = (
    <span className="flex items-center gap-1.5">
      <code className="font-mono text-[12px]">{param.name}</code>
      {param.required && <Badge tone="warning">required</Badge>}
      {param.secret && <Badge tone="info">environment variable</Badge>}
    </span>
  );
  if (param.type === "bool" && !param.secret) {
    const checked = typeof value === "boolean" ? value : param.default === true;
    return (
      <Switch
        label={label}
        description={param.description || undefined}
        checked={checked}
        onCheckedChange={(next) => {
          onChange(param.name, next);
        }}
      />
    );
  }
  return (
    <label className="flex flex-col gap-1 text-[12.5px]">
      {label}
      {param.description && <span className="text-fg-muted">{param.description}</span>}
      {param.type === "choice" && !param.secret ? (
        <select
          aria-label={param.name}
          className="h-8 rounded-control border border-border-input bg-surface px-2 text-[12.5px]"
          value={typeof value === "string" ? value : ""}
          onChange={(event) => {
            onChange(param.name, event.target.value);
          }}
        >
          <option value="">Default</option>
          {param.choices.map((choice) => (
            <option key={String(choice)} value={String(choice)}>
              {String(choice)}
            </option>
          ))}
        </select>
      ) : (
        <Input
          aria-label={param.name}
          className={cn(param.secret && "font-mono")}
          placeholder={param.secret ? "ENV_VAR_NAME" : placeholderOf(param.default)}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => {
            onChange(param.name, param.secret ? event.target.value.toUpperCase() : event.target.value);
          }}
        />
      )}
    </label>
  );
}

function placeholderOf(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return typeof value === "number" || typeof value === "boolean" ? String(value) : JSON.stringify(value);
}
