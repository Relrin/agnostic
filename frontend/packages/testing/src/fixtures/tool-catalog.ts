// The sample org's tool catalog: Linear and web search for everyone, the Data team's own search and a warehouse MCP
// server, and a custom Slack toolkit a builder set up on staging. Plain data, shared by the unit tests and e2e.
import type { EntryOut, RegistryEntryOut, SyncStatusOut, ToolkitOut } from "@agnostic/api";

const T = "2026-11-01T09:00:00Z";

function catalogEntry(
  fields: Partial<EntryOut> & Pick<EntryOut, "id" | "slug" | "registry_name" | "display_name">,
): EntryOut {
  return {
    level: "org",
    level_label: "Organization",
    owner_group_id: null,
    owner_group_name: null,
    description: "",
    icon: null,
    kind: "mcp",
    transport: "streamable-http",
    toolkit_key: null,
    config: {},
    requires_confirmation_tools: [],
    instance_ids: [],
    status: "active",
    local: false,
    version: 1,
    editable: true,
    same_as: [],
    created_by: "usr_dana",
    created_at: T,
    updated_at: T,
    ...fields,
  };
}

export const catalogEntries: EntryOut[] = [
  catalogEntry({
    id: "tce_linear",
    slug: "linear",
    registry_name: "org-linear",
    display_name: "Linear",
    description: "Issues, projects and cycles from the company's Linear workspace.",
    config: {
      url: "https://mcp.linear.app/mcp",
      headers: { Authorization: { env: "LINEAR_TOKEN", format: "Bearer {}" } },
      tool_name_prefix: "org_linear_",
      include_tools: [],
      exclude_tools: ["delete_issue"],
      timeout_seconds: 10,
      transport: "streamable-http",
    },
  }),
  catalogEntry({
    id: "tce_search",
    slug: "search",
    registry_name: "org-search",
    display_name: "Web search",
    description: "DuckDuckGo search and news, safe search on.",
    kind: "toolkit",
    transport: null,
    toolkit_key: "duck_duck_go",
    config: { params: { region: "us-en" } },
    same_as: [
      {
        entry_id: "tce_data_search",
        registry_name: "team-data-search",
        level: "team",
        level_label: "Team · Data",
        display_name: "Data search",
      },
    ],
  }),
  catalogEntry({
    id: "tce_data_search",
    slug: "search",
    registry_name: "team-data-search",
    display_name: "Data search",
    description: "Search tuned for the data team: news off, 20 results.",
    level: "team",
    level_label: "Team · Data",
    owner_group_id: "grp_data",
    owner_group_name: "Data",
    kind: "toolkit",
    transport: null,
    toolkit_key: "duck_duck_go",
    config: { params: { enable_news: false, fixed_max_results: 20 } },
    same_as: [
      {
        entry_id: "tce_search",
        registry_name: "org-search",
        level: "org",
        level_label: "Organization",
        display_name: "Web search",
      },
    ],
  }),
  catalogEntry({
    id: "tce_warehouse",
    slug: "warehouse",
    registry_name: "team-data-warehouse",
    display_name: "Warehouse",
    description: "Read-only SQL over the analytics warehouse.",
    level: "team",
    level_label: "Team · Data",
    owner_group_id: "grp_data",
    owner_group_name: "Data",
    transport: "sse",
    config: { url: "https://warehouse-mcp.internal/sse", headers: { "X-Api-Key": { env: "WAREHOUSE_KEY" } } },
  }),
  catalogEntry({
    id: "tce_slack",
    slug: "slack",
    registry_name: "custom-k2p9q7-slack",
    display_name: "Support Slack",
    description: "Posts escalations to #support-escalations.",
    level: "custom",
    level_label: "Custom",
    kind: "toolkit",
    transport: null,
    toolkit_key: "slack",
    config: { params: { token: { env: "SLACK_BOT_TOKEN" } } },
    instance_ids: ["ins_01M6A0EEZEQ373S26F2014STG"],
  }),
];

function param(name: string, type: string, extra: Partial<ToolkitOut["params"][number]> = {}) {
  return {
    name,
    type,
    required: false,
    default: null,
    choices: [],
    secret: false,
    description: "",
    ...extra,
  };
}

function toolkit(fields: Partial<ToolkitOut> & Pick<ToolkitOut, "key" | "label" | "category">): ToolkitOut {
  return { description: "", local: false, extra: null, params: [], importable: true, ...fields };
}

export const catalogToolkits: ToolkitOut[] = [
  toolkit({
    key: "duck_duck_go",
    label: "DuckDuckGo",
    category: "search",
    description: "Web and news search with DuckDuckGo.",
    extra: "ddgs",
    params: [
      param("enable_news", "bool", { default: true, description: "Enable news search function." }),
      param("region", "str", { description: "Region for search results (e.g., us-en, uk-en)." }),
      param("fixed_max_results", "int", { description: "A fixed number of maximum results." }),
    ],
  }),
  toolkit({
    key: "wikipedia",
    label: "Wikipedia",
    category: "search",
    description: "Search and read Wikipedia.",
  }),
  toolkit({
    key: "tavily",
    label: "Tavily",
    category: "search",
    description: "AI search with sources.",
    extra: "tavily-python",
    params: [param("api_key", "str", { secret: true, description: "Tavily API key." })],
  }),
  toolkit({
    key: "github",
    label: "GitHub",
    category: "productivity",
    description: "Repositories, issues and pull requests.",
    extra: "pygithub",
    importable: false,
    params: [
      param("access_token", "str", { secret: true, description: "A GitHub token." }),
      param("base_url", "str", { description: "GitHub Enterprise API URL." }),
    ],
  }),
  toolkit({
    key: "slack",
    label: "Slack",
    category: "social",
    description: "Send and read Slack messages.",
    extra: "slack-sdk",
    params: [param("token", "str", { secret: true, description: "The Slack API token." })],
  }),
  toolkit({
    key: "shell",
    label: "Shell",
    category: "local",
    description: "Run shell commands.",
    local: true,
  }),
];

function catalogTool(
  name: string,
  info: NonNullable<RegistryEntryOut["catalog"]>,
  functions: string[],
  description: string,
): RegistryEntryOut {
  const available = info.state === "connected";
  return {
    type: "tool",
    name,
    id: null,
    description,
    blurb: description,
    meta: `${info.kind === "mcp" ? "MCP server" : "Agno toolkit"} · ${info.level_label}`,
    status: "registered",
    details: [],
    code: null,
    code_label: null,
    requires_approval: false,
    approval_type: null,
    studio_available: available,
    availability: available
      ? { kind: "available", title: "Available in Studio.", text: "From the tool catalog." }
      : {
          kind: "unavailable",
          title: "Not on this instance yet.",
          text: "The runtime hasn't pulled it yet.",
        },
    functions: functions.map((fn) => ({
      name: fn,
      description: null,
      parameters: { type: "object", properties: {}, required: [] },
      signature: null,
      requires_confirmation: false,
    })),
    source: null,
    catalog: info,
    used_by_count: 0,
    config_value: functions.map((fn) => ({
      name: fn,
      parameters: { type: "object", properties: {}, required: [] },
      toolkit: name,
    })),
  };
}

const info = (
  fields: Partial<NonNullable<RegistryEntryOut["catalog"]>>,
): NonNullable<RegistryEntryOut["catalog"]> => ({
  entry_id: "tce",
  level: "org",
  level_label: "Organization",
  display_name: "",
  kind: "mcp",
  state: "connected",
  icon: null,
  transport: null,
  toolkit_key: null,
  detail: null,
  same_as: [],
  ...fields,
});

/** Registry tools from the catalog, as Studio's registry lists them on staging. */
export const catalogRegistryTools: RegistryEntryOut[] = [
  catalogTool(
    "org-linear",
    info({ entry_id: "tce_linear", display_name: "Linear", transport: "streamable-http" }),
    ["org_linear_list_issues", "org_linear_create_issue", "org_linear_search"],
    "Issues, projects and cycles from the company's Linear workspace.",
  ),
  catalogTool(
    "org-search",
    info({
      entry_id: "tce_search",
      display_name: "Web search",
      kind: "toolkit",
      toolkit_key: "duck_duck_go",
      same_as: ["team-data-search"],
    }),
    ["duckduckgo_search", "duckduckgo_news"],
    "DuckDuckGo search and news, safe search on.",
  ),
  catalogTool(
    "team-data-search",
    info({
      entry_id: "tce_data_search",
      level: "team",
      level_label: "Team · Data",
      display_name: "Data search",
      kind: "toolkit",
      toolkit_key: "duck_duck_go",
      same_as: ["org-search"],
    }),
    ["duckduckgo_search"],
    "Search tuned for the data team.",
  ),
  catalogTool(
    "team-data-warehouse",
    info({
      entry_id: "tce_warehouse",
      level: "team",
      level_label: "Team · Data",
      display_name: "Warehouse",
      transport: "sse",
      state: "missing_env",
      detail: "Set WAREHOUSE_KEY on the runtime.",
    }),
    [],
    "Read-only SQL over the analytics warehouse.",
  ),
  catalogTool(
    "custom-k2p9q7-slack",
    info({
      entry_id: "tce_slack",
      level: "custom",
      level_label: "Custom",
      display_name: "Support Slack",
      kind: "toolkit",
      toolkit_key: "slack",
      state: "not_on_instance",
    }),
    [],
    "Posts escalations to #support-escalations.",
  ),
];

export const catalogSyncStatus: SyncStatusOut = {
  instance_id: "ins_01M6A0EEZEQ373S26F2014STG",
  instance_name: "staging-agentos",
  last_pulled_at: T,
  entries: 4,
  bridge_version: "0.2.0",
  reachable: true,
  bridge: {
    enabled: true,
    local_allowed: false,
    interval_seconds: 60,
    last_sync_at: T,
    last_error: null,
    replica_id: "staging-agentos-7c9:1",
    entries: [
      {
        name: "org-linear",
        state: "connected",
        detail: null,
        functions: ["org_linear_list_issues", "org_linear_search"],
      },
      {
        name: "org-search",
        state: "connected",
        detail: null,
        functions: ["duckduckgo_search", "duckduckgo_news"],
      },
      { name: "team-data-search", state: "connected", detail: null, functions: ["duckduckgo_search"] },
      {
        name: "team-data-warehouse",
        state: "missing_env",
        detail: "Set WAREHOUSE_KEY on the runtime.",
        functions: [],
      },
    ],
  },
};
