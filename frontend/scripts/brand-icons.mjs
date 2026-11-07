// Writes packages/ui/src/brand/glyphs.gen.ts: the brand logos the UI shows for AI model providers, MCP servers and
// Agno toolkits, copied out of two icon sets so the bundle carries only the few dozen logos it uses (and works
// without network access):
//
//   simple-icons               CC0-1.0  https://simpleicons.org          applications and developer tools
//   @lobehub/icons-static-svg  MIT      https://lobehub.com/icons        AI model providers and AI services
//
// Each logo comes in two versions: monochrome (filled with the current text color) and in the brand's own colors
// (Lobe's color SVG, or simple-icons' brand color). A brand color too dark to see on the dark theme's surfaces
// (GitHub's near-black, X's black) falls back to the text color, the way those brands draw on dark backgrounds.
// Run `node scripts/brand-icons.mjs` after changing BRANDS (or bumping either set), and commit the output.
// `--check` fails when the committed file is out of date (CI).
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import prettier from "prettier";

const frontend = fileURLToPath(new URL("..", import.meta.url));
const ui = join(frontend, "packages", "ui");
const output = join(ui, "src", "brand", "glyphs.gen.ts");
const require = createRequire(join(ui, "package.json"));

/** The installed package's folder (its `exports` hide package.json from require.resolve). */
function packageRoot(name) {
  const found = (require.resolve.paths(name) ?? [])
    .map((base) => join(base, name))
    .find((candidate) => existsSync(join(candidate, "package.json")));
  if (!found) throw new Error(`${name} is not installed: run yarn install`);
  return found;
}

const SETS = {
  si: { root: packageRoot("simple-icons"), name: "simple-icons" },
  lobe: { root: packageRoot("@lobehub/icons-static-svg"), name: "@lobehub/icons-static-svg" },
};

/**
 * Brand id → [set, file name in the set's icons/ folder, options]. Ids are what `icon` fields and the maps in
 * brands.ts use. `mono: true` skips the color version (Lobe's Antigravity draws with filters and masks).
 */
const BRANDS = {
  // AI model providers and AI services
  alibaba: ["lobe", "alibaba"],
  anthropic: ["lobe", "anthropic"],
  antigravity: ["lobe", "antigravity", { mono: true }],
  aws: ["lobe", "aws"],
  azure: ["lobe", "azure"],
  baidu: ["lobe", "baidu"],
  bedrock: ["lobe", "bedrock"],
  brave: ["lobe", "brave"],
  cerebras: ["lobe", "cerebras"],
  cohere: ["lobe", "cohere"],
  dalle: ["lobe", "dalle"],
  deepinfra: ["lobe", "deepinfra"],
  deepseek: ["lobe", "deepseek"],
  elevenlabs: ["lobe", "elevenlabs"],
  exa: ["lobe", "exa"],
  fal: ["lobe", "fal"],
  firecrawl: ["lobe", "firecrawl"],
  fireworks: ["lobe", "fireworks"],
  gemini: ["lobe", "gemini"],
  google: ["lobe", "google"],
  groq: ["lobe", "groq"],
  huggingface: ["lobe", "huggingface"],
  ibm: ["lobe", "ibm"],
  jina: ["lobe", "jina"],
  lmstudio: ["lobe", "lmstudio"],
  luma: ["lobe", "luma"],
  mcp: ["lobe", "mcp"],
  meta: ["lobe", "meta"],
  microsoft: ["lobe", "microsoft"],
  minimax: ["lobe", "minimax"],
  mistral: ["lobe", "mistral"],
  moonshot: ["lobe", "moonshot"],
  nanobanana: ["lobe", "nanobanana"],
  nebius: ["lobe", "nebius"],
  nvidia: ["lobe", "nvidia"],
  ollama: ["lobe", "ollama"],
  openai: ["lobe", "openai"],
  openrouter: ["lobe", "openrouter"],
  perplexity: ["lobe", "perplexity"],
  qwen: ["lobe", "qwen"],
  replicate: ["lobe", "replicate"],
  sambanova: ["lobe", "sambanova"],
  searchapi: ["lobe", "searchapi"],
  searxng: ["lobe", "searxng"],
  tavily: ["lobe", "tavily"],
  together: ["lobe", "together"],
  vercel: ["lobe", "vercel"],
  vertexai: ["lobe", "vertexai"],
  vllm: ["lobe", "vllm"],
  wavespeed: ["lobe", "wavespeed"],
  xai: ["lobe", "xai"],
  zhipu: ["lobe", "zhipu"],
  // Applications and developer tools
  airflow: ["si", "apacheairflow"],
  arxiv: ["si", "arxiv"],
  bash: ["si", "gnubash"],
  bitbucket: ["si", "bitbucket"],
  brandfetch: ["si", "brandfetch"],
  calcom: ["si", "caldotcom"],
  clickup: ["si", "clickup"],
  confluence: ["si", "confluence"],
  discord: ["si", "discord"],
  docker: ["si", "docker"],
  duckdb: ["si", "duckdb"],
  duckduckgo: ["si", "duckduckgo"],
  ethereum: ["si", "ethereum"],
  giphy: ["si", "giphy"],
  github: ["si", "github"],
  gitlab: ["si", "gitlab"],
  gmail: ["si", "gmail"],
  googlebigquery: ["si", "googlebigquery"],
  googlecalendar: ["si", "googlecalendar"],
  googledrive: ["si", "googledrive"],
  googlemaps: ["si", "googlemaps"],
  googlesheets: ["si", "googlesheets"],
  googleslides: ["si", "googleslides"],
  hackernews: ["si", "ycombinator"],
  jira: ["si", "jira"],
  linear: ["si", "linear"],
  mysql: ["si", "mysql"],
  neo4j: ["si", "neo4j"],
  notion: ["si", "notion"],
  opencv: ["si", "opencv"],
  pandas: ["si", "pandas"],
  postgres: ["si", "postgresql"],
  pubmed: ["si", "pubmed"],
  python: ["si", "python"],
  reddit: ["si", "reddit"],
  redmine: ["si", "redmine"],
  resend: ["si", "resend"],
  shopify: ["si", "shopify"],
  spotify: ["si", "spotify"],
  sqlite: ["si", "sqlite"],
  telegram: ["si", "telegram"],
  todoist: ["si", "todoist"],
  trello: ["si", "trello"],
  unsplash: ["si", "unsplash"],
  webex: ["si", "webex"],
  whatsapp: ["si", "whatsapp"],
  wikipedia: ["si", "wikipedia"],
  x: ["si", "x"],
  youtube: ["si", "youtube"],
  zendesk: ["si", "zendesk"],
  zoom: ["si", "zoom"],
};

/** Path attributes kept (camelCased for React); anything else in a logo fails the run, so nothing slips in. */
const PATH_ATTRIBUTES = {
  d: "d",
  fill: "fill",
  "fill-rule": "fillRule",
  "clip-rule": "clipRule",
  "fill-opacity": "fillOpacity",
  opacity: "opacity",
  transform: "transform",
};
const GRADIENT_ATTRIBUTES = {
  x1: "x1",
  x2: "x2",
  y1: "y1",
  y2: "y2",
  gradientUnits: "gradientUnits",
  gradientTransform: "gradientTransform",
};
const STOP_ATTRIBUTES = { offset: "offset", "stop-color": "stopColor", "stop-opacity": "stopOpacity" };
const SKIPPED = new Set(["title", "defs"]);

/** The lightest dark surface a logo sits on (--surface-hover): a fill must stand out from it to keep its color. */
const SURFACE = "#1a1d22";
const MIN_CONTRAST = 2;

function luminance(hex) {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? [...value].map((char) => char + char).join("") : value;
  const [r, g, b] = [0, 2, 4].map((index) => {
    const channel = Number.parseInt(full.slice(index, index + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** A solid fill visible on the dark surfaces keeps its color; a darker one draws in the text color. */
function visible(fill) {
  if (!/^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(fill)) return fill;
  const [light, dark] = [luminance(fill), luminance(SURFACE)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05) >= MIN_CONTRAST ? fill.toUpperCase() : "currentColor";
}

function attributes(text) {
  return Object.fromEntries(
    [...text.matchAll(/([a-zA-Z:-][a-zA-Z0-9:-]*)="([^"]*)"/g)].map((match) => [match[1], match[2]]),
  );
}

function pick(id, element, raw, allowed) {
  const picked = {};
  for (const [name, value] of Object.entries(raw)) {
    // Luma blends its layers: the one inline style a logo may carry.
    const blend =
      element === "path" && name === "style" ? /^mix-blend-mode:\s*([a-z-]+);?$/.exec(value) : null;
    if (blend) {
      picked.mixBlendMode = blend[1];
      continue;
    }
    const key = allowed[name];
    if (!key) throw new Error(`${id}: attribute ${name} on <${element}> is not supported`);
    picked[key] = value;
  }
  return picked;
}

/** An SVG file as its title, viewBox, paths and linear gradients (gradient references become `url(#g<index>)`). */
function parse(id, path) {
  const svg = readFileSync(path, "utf8").trim();
  const root = /^<svg\b([^>]*)>([\s\S]*)<\/svg>$/.exec(svg);
  if (!root) throw new Error(`${id}: ${path} is not a single <svg> element`);
  const rootAttributes = attributes(root[1]);
  const title = /<title>([^<]*)<\/title>/.exec(root[2])?.[1] ?? id;
  const body = root[2].replace(/<title>[^<]*<\/title>/, "");
  const paths = [];
  const gradients = [];
  const gradientIds = new Map();
  let gradient;
  for (const tag of body.matchAll(/<(\/?)([a-zA-Z]+)\b([^>]*?)(\/?)>/g)) {
    const [, closing, element, rawAttributes, selfClosing] = tag;
    if (SKIPPED.has(element)) continue;
    if (closing) {
      if (element === "linearGradient") gradient = undefined;
      continue;
    }
    const raw = attributes(rawAttributes);
    if (element === "path") {
      const picked = pick(id, element, raw, PATH_ATTRIBUTES);
      if (rootAttributes["fill-rule"] && !picked.fillRule) picked.fillRule = rootAttributes["fill-rule"];
      paths.push(picked);
    } else if (element === "linearGradient") {
      const { id: gradientId, ...rest } = raw;
      gradientIds.set(gradientId, gradients.length);
      gradient = { ...pick(id, element, rest, GRADIENT_ATTRIBUTES), stops: [] };
      gradients.push(gradient);
      if (selfClosing) gradient = undefined;
    } else if (element === "stop" && gradient) {
      gradient.stops.push(pick(id, element, raw, STOP_ATTRIBUTES));
    } else {
      throw new Error(`${id}: <${element}> in ${path} is not supported`);
    }
  }
  for (const item of paths) {
    const reference = /^url\(#(.+)\)$/.exec(item.fill ?? "");
    if (!reference) continue;
    const index = gradientIds.get(reference[1]);
    if (index === undefined) throw new Error(`${id}: ${path} fills with a missing gradient ${reference[1]}`);
    item.fill = `url(#g${String(index)})`;
  }
  if (paths.length === 0) throw new Error(`${id}: no paths in ${path}`);
  return { title: decode(title), viewBox: rootAttributes.viewBox ?? "0 0 24 24", paths, gradients };
}

/** Monochrome paths draw in the text color: their own black or currentColor fills go. */
function mono(id, paths) {
  return paths.map(({ fill, ...rest }) => {
    if (fill && !/^(currentColor|#000|#000000)$/i.test(fill)) {
      throw new Error(`${id}: a monochrome path fills with ${fill}`);
    }
    return rest;
  });
}

let simpleIconColors;

/** simple-icons' brand color for a file name (its slug). */
function simpleIconColor(file) {
  simpleIconColors ??= new Map(
    JSON.parse(readFileSync(join(SETS.si.root, "data", "simple-icons.json"), "utf8")).map((icon) => [
      icon.slug,
      `#${icon.hex}`,
    ]),
  );
  return simpleIconColors.get(file);
}

function glyphOf(id, [set, file, options = {}]) {
  const base = parse(id, join(SETS[set].root, "icons", `${file}.svg`));
  const glyph = {
    title: base.title,
    viewBox: base.viewBox,
    source: SETS[set].name,
    paths: mono(id, base.paths),
  };
  if (options.mono) return glyph;
  if (set === "si") {
    const color = simpleIconColor(file);
    if (!color) throw new Error(`${id}: simple-icons has no color for ${file}`);
    return { ...glyph, color: { fill: visible(color) } };
  }
  const colorFile = join(SETS[set].root, "icons", `${file}-color.svg`);
  if (!existsSync(colorFile)) return glyph;
  const colored = parse(id, colorFile);
  return {
    ...glyph,
    color: {
      paths: colored.paths.map((path) => ({ ...path, fill: visible(path.fill ?? "#000000") })),
      gradients: colored.gradients,
    },
  };
}

function decode(text) {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');
}

function version(set) {
  return JSON.parse(readFileSync(join(SETS[set].root, "package.json"), "utf8")).version;
}

const ids = Object.keys(BRANDS).sort();
const glyphs = Object.fromEntries(ids.map((id) => [id, glyphOf(id, BRANDS[id])]));
const text = `// Generated by scripts/brand-icons.mjs from simple-icons ${version("si")} (CC0-1.0) and
// @lobehub/icons-static-svg ${version("lobe")} (MIT). Do not edit: change BRANDS there and run it again.
// Logos are trademarks of their owners and show here only to name the service a tool talks to.

export type BrandPath = {
  d: string;
  /** A color, currentColor, or url(#g<index>): the glyph's gradient at that index. */
  fill?: string;
  fillRule?: "nonzero" | "evenodd";
  clipRule?: "nonzero" | "evenodd";
  fillOpacity?: string;
  opacity?: string;
  transform?: string;
  mixBlendMode?: "screen" | "overlay" | "multiply";
};

export type BrandGradient = {
  x1?: string;
  x2?: string;
  y1?: string;
  y2?: string;
  gradientUnits?: "userSpaceOnUse" | "objectBoundingBox";
  gradientTransform?: string;
  stops: readonly { offset?: string; stopColor?: string; stopOpacity?: string }[];
};

export type BrandGlyph = {
  title: string;
  viewBox: string;
  source: string;
  /** Monochrome: drawn in the current text color. */
  paths: readonly BrandPath[];
  /**
   * In the brand's own colors, when the set has them: the monochrome paths in one \`fill\` (simple-icons), or
   * paths of their own with gradients (Lobe).
   */
  color?:
    | { fill: string; paths?: undefined; gradients?: undefined }
    | { fill?: undefined; paths: readonly BrandPath[]; gradients: readonly BrandGradient[] };
};

export const BRAND_IDS = ${JSON.stringify(ids)} as const;

export type BrandId = (typeof BRAND_IDS)[number];

export const BRAND_GLYPHS: Record<BrandId, BrandGlyph> = ${JSON.stringify(glyphs)};
`;

const formatted = await prettier.format(text, {
  ...(await prettier.resolveConfig(output)),
  filepath: output,
});

if (process.argv.includes("--check")) {
  let current = "";
  try {
    current = readFileSync(output, "utf8");
  } catch {
    // missing: out of date
  }
  if (current !== formatted) {
    console.error("packages/ui/src/brand/glyphs.gen.ts is out of date: run node scripts/brand-icons.mjs");
    process.exit(1);
  }
} else {
  writeFileSync(output, formatted);
  console.log(`wrote ${String(ids.length)} brand glyphs to ${output}`);
}
