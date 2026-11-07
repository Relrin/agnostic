// Which brand logo a tool or a model shows. A catalog entry can name its logo (`icon`); otherwise an Agno toolkit
// shows its service's logo, an MCP server the logo its name, URL or command points at, and a model its provider's.
// Anything without a known brand falls back to a generic glyph chosen by the caller.
import { BRAND_GLYPHS, BRAND_IDS, type BrandId } from "./glyphs.gen";

export function isBrandId(value: unknown): value is BrandId {
  return typeof value === "string" && value in BRAND_GLYPHS;
}

/** Brands a builder can pick for a catalog entry, by display name. */
export const BRAND_OPTIONS: readonly { id: BrandId; title: string }[] = BRAND_IDS.map((id) => ({
  id,
  title: BRAND_GLYPHS[id].title,
})).sort((a, b) => a.title.localeCompare(b.title));

/** Agno toolkit key → the brand of the service it talks to. Toolkits missing here are generic (shell, csv, sql…). */
export const TOOLKIT_BRANDS: Readonly<Record<string, BrandId>> = {
  airflow: "airflow",
  antigravity: "antigravity",
  arxiv: "arxiv",
  aws_lambda: "aws",
  awsses: "aws",
  baidu_search: "baidu",
  bitbucket: "bitbucket",
  brandfetch: "brandfetch",
  brave_search: "brave",
  cal_com: "calcom",
  click_up: "clickup",
  confluence: "confluence",
  dalle: "dalle",
  discord: "discord",
  docker: "docker",
  duck_db: "duckdb",
  duck_duck_go: "duckduckgo",
  eleven_labs: "elevenlabs",
  evm: "ethereum",
  exa: "exa",
  fal: "fal",
  firecrawl: "firecrawl",
  giphy: "giphy",
  github: "github",
  gitlab: "gitlab",
  gmail: "gmail",
  google_big_query: "googlebigquery",
  google_calendar: "googlecalendar",
  google_drive: "googledrive",
  google_map: "googlemaps",
  google_sheets: "googlesheets",
  google_slides: "googleslides",
  hacker_news: "hackernews",
  jina_reader: "jina",
  jira: "jira",
  linear: "linear",
  luma_lab: "luma",
  mini_max: "minimax",
  nano_banana: "nanobanana",
  neo4j: "neo4j",
  notion: "notion",
  open_ai: "openai",
  open_cv: "opencv",
  pandas: "pandas",
  perplexity_search: "perplexity",
  postgres: "postgres",
  pubmed: "pubmed",
  python: "python",
  reddit: "reddit",
  redmine: "redmine",
  replicate: "replicate",
  resend: "resend",
  search_api: "searchapi",
  searxng: "searxng",
  shell: "bash",
  shopify: "shopify",
  spotify: "spotify",
  tavily: "tavily",
  telegram: "telegram",
  todoist: "todoist",
  trello: "trello",
  unsplash: "unsplash",
  wave_speed: "wavespeed",
  webex: "webex",
  whats_app: "whatsapp",
  wikipedia: "wikipedia",
  x: "x",
  you_tube: "youtube",
  zendesk: "zendesk",
  zoom: "zoom",
};

/**
 * Words that name a brand in an MCP server's name, URL or command (`mcp.linear.app`, `@notionhq/notion-mcp-server`,
 * "GitHub (org)"). Matched as whole words, longest first, so "google drive" wins over "google".
 */
const BRAND_WORDS: readonly (readonly [string, BrandId])[] = (
  [
    ["airflow", "airflow"],
    ["alibaba", "alibaba"],
    ["anthropic", "anthropic"],
    ["arxiv", "arxiv"],
    ["aws", "aws"],
    ["amazon", "aws"],
    ["azure", "azure"],
    ["bedrock", "bedrock"],
    ["bigquery", "googlebigquery"],
    ["bitbucket", "bitbucket"],
    ["brave", "brave"],
    ["cal.com", "calcom"],
    ["claude", "anthropic"],
    ["clickup", "clickup"],
    ["confluence", "confluence"],
    ["atlassian", "jira"],
    ["discord", "discord"],
    ["docker", "docker"],
    ["duckdb", "duckdb"],
    ["duckduckgo", "duckduckgo"],
    ["elevenlabs", "elevenlabs"],
    ["exa", "exa"],
    ["firecrawl", "firecrawl"],
    ["gemini", "gemini"],
    ["github", "github"],
    ["gitlab", "gitlab"],
    ["gmail", "gmail"],
    ["google", "google"],
    ["google calendar", "googlecalendar"],
    ["google drive", "googledrive"],
    ["google maps", "googlemaps"],
    ["google sheets", "googlesheets"],
    ["google slides", "googleslides"],
    ["gdrive", "googledrive"],
    ["huggingface", "huggingface"],
    ["hugging face", "huggingface"],
    ["jina", "jina"],
    ["jira", "jira"],
    ["linear", "linear"],
    ["microsoft", "microsoft"],
    ["mysql", "mysql"],
    ["neo4j", "neo4j"],
    ["notion", "notion"],
    ["notionhq", "notion"],
    ["openai", "openai"],
    ["perplexity", "perplexity"],
    ["postgres", "postgres"],
    ["postgresql", "postgres"],
    ["reddit", "reddit"],
    ["replicate", "replicate"],
    ["shopify", "shopify"],
    ["spotify", "spotify"],
    ["sqlite", "sqlite"],
    ["tavily", "tavily"],
    ["telegram", "telegram"],
    ["todoist", "todoist"],
    ["trello", "trello"],
    ["vercel", "vercel"],
    ["whatsapp", "whatsapp"],
    ["wikipedia", "wikipedia"],
    ["youtube", "youtube"],
    ["zendesk", "zendesk"],
    ["zoom", "zoom"],
  ] as const
)
  .slice()
  .sort((a, b) => b[0].length - a[0].length);

/** "@notionhq/notion-mcp-server" → " notionhq notion mcp server ", "https://mcp.linear.app/sse" → " https mcp linear app sse ". */
function words(text: string): string {
  return ` ${text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()} `;
}

/** The brand a free text names (an MCP server's name, URL or command), if any. */
export function brandInText(...texts: readonly (string | null | undefined)[]): BrandId | undefined {
  for (const text of texts) {
    if (!text) continue;
    const haystack = words(text);
    const found = BRAND_WORDS.find(([word]) => haystack.includes(words(word)));
    if (found) return found[1];
  }
  return undefined;
}

export type ToolBrandInput = {
  /** The logo a catalog entry names. */
  icon?: string | null | undefined;
  kind?: "mcp" | "toolkit" | undefined;
  toolkitKey?: string | null | undefined;
  /** Display or registry name, URL, command…: searched for a brand's name when nothing else says. */
  hints?: readonly (string | null | undefined)[];
};

/** The brand logo of a tool, or undefined for a generic glyph. */
export function toolBrand(tool: ToolBrandInput): BrandId | undefined {
  if (isBrandId(tool.icon)) return tool.icon;
  if (tool.toolkitKey) {
    const known = TOOLKIT_BRANDS[tool.toolkitKey];
    if (known) return known;
    // A toolkit without a brand of its own (csv, calculator…) stays generic: its name can't mislead.
    if (tool.kind === "toolkit") return undefined;
  }
  return brandInText(...(tool.hints ?? []));
}

/** Agno model provider names (`model.provider`, `openai:gpt-5` prefixes) → brand. Compared without punctuation. */
const PROVIDER_BRANDS: Readonly<Record<string, BrandId>> = {
  aimlapi: "openai",
  alibaba: "alibaba",
  anthropic: "anthropic",
  aws: "aws",
  awsbedrock: "bedrock",
  azure: "azure",
  azureaifoundry: "azure",
  azureopenai: "azure",
  bedrock: "bedrock",
  cerebras: "cerebras",
  cerebrasopenai: "cerebras",
  claude: "anthropic",
  cohere: "cohere",
  dashscope: "qwen",
  deepinfra: "deepinfra",
  deepseek: "deepseek",
  fireworks: "fireworks",
  gemini: "gemini",
  google: "gemini",
  googlevertex: "vertexai",
  groq: "groq",
  huggingface: "huggingface",
  ibm: "ibm",
  ibmwatsonx: "ibm",
  lmstudio: "lmstudio",
  meta: "meta",
  llama: "meta",
  llamaopenai: "meta",
  mistral: "mistral",
  mistralai: "mistral",
  moonshot: "moonshot",
  nebius: "nebius",
  nvidia: "nvidia",
  ollama: "ollama",
  openai: "openai",
  openaichat: "openai",
  openairesponses: "openai",
  openrouter: "openrouter",
  perplexity: "perplexity",
  qwen: "qwen",
  sambanova: "sambanova",
  together: "together",
  vercel: "vercel",
  vertexai: "vertexai",
  vllm: "vllm",
  watsonx: "ibm",
  xai: "xai",
  zhipu: "zhipu",
};

/** Model id prefixes that name their maker when the provider doesn't (an OpenRouter or Ollama id says less). */
const MODEL_PREFIXES: readonly (readonly [RegExp, BrandId])[] = [
  [/^(gpt|o\d|chatgpt|dall-e|text-embedding)/, "openai"],
  [/^claude/, "anthropic"],
  [/^(gemini|gemma)/, "gemini"],
  [/^(mistral|mixtral|codestral|ministral|magistral|devstral)/, "mistral"],
  [/^(llama|meta-llama)/, "meta"],
  [/^(qwen|qwq)/, "qwen"],
  [/^deepseek/, "deepseek"],
  [/^grok/, "xai"],
  [/^command/, "cohere"],
  [/^(glm|chatglm)/, "zhipu"],
  [/^(kimi|moonshot)/, "moonshot"],
  [/^(nemotron|nvidia)/, "nvidia"],
];

function compact(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** The brand of a model: its provider's, else the maker its id names (`claude-…`, `openai/gpt-…`, `openai:gpt-…`). */
export function modelBrand(model: {
  provider?: string | null | undefined;
  id?: string | null | undefined;
}): BrandId | undefined {
  const provider = model.provider ? PROVIDER_BRANDS[compact(model.provider)] : undefined;
  if (provider) return provider;
  const id = (model.id ?? "").toLowerCase();
  const [prefix, rest] = /[:/]/.test(id) ? id.split(/[:/]/, 2) : [undefined, id];
  const named = prefix ? PROVIDER_BRANDS[compact(prefix)] : undefined;
  if (named) return named;
  // "qwen3:8b" (an Ollama tag) or "meta-llama/llama-4": the maker leads the id.
  const maker = (text: string) => MODEL_PREFIXES.find(([pattern]) => pattern.test(text))?.[1];
  return maker(id) ?? (rest ? maker(rest) : undefined);
}
