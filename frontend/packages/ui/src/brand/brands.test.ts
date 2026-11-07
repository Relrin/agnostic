// Which logo a tool or a model gets: a catalog entry's own pick, its toolkit's service, the brand an MCP server's
// name, URL or command names, a model's provider or maker; and every mapped logo exists.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { TOOLKIT_BRANDS, brandInText, isBrandId, modelBrand, toolBrand } from "./brands";
import { BRAND_GLYPHS, BRAND_IDS } from "./glyphs.gen";

/** The Agno toolkit list the control plane serves (written from the bridge, so it matches what runtimes build). */
const SPEC = "backend/packages/agnostic-spec/src/agnostic_spec/toolkits.json";
// Vitest runs from the frontend root (or packages/ui when run there).
const toolkitList = ["..", "../../.."]
  .map((up) => join(process.cwd(), up, SPEC))
  .find((candidate) => existsSync(candidate));

describe("toolBrand", () => {
  it("prefers the entry's own pick, then its toolkit's service", () => {
    expect(toolBrand({ icon: "notion", kind: "toolkit", toolkitKey: "github" })).toBe("notion");
    expect(toolBrand({ kind: "toolkit", toolkitKey: "github", hints: ["Docs"] })).toBe("github");
    // An unknown pick (a logo removed from the set) falls back to what the tool is.
    expect(toolBrand({ icon: "nope", kind: "toolkit", toolkitKey: "google_sheets" })).toBe("googlesheets");
  });

  it("keeps a generic toolkit generic whatever it is called", () => {
    expect(toolBrand({ kind: "toolkit", toolkitKey: "csv", hints: ["GitHub exports"] })).toBeUndefined();
  });

  it("finds an MCP server's brand in its name, URL or command", () => {
    expect(toolBrand({ kind: "mcp", hints: ["Issues", "https://mcp.linear.app/sse"] })).toBe("linear");
    expect(toolBrand({ kind: "mcp", hints: ["Docs", "npx -y @notionhq/notion-mcp-server"] })).toBe("notion");
    expect(toolBrand({ kind: "mcp", hints: ["Warehouse", "https://mcp.internal/sse"] })).toBeUndefined();
  });

  it("matches whole words, the longest name first", () => {
    expect(brandInText("Google Drive files")).toBe("googledrive");
    expect(brandInText("Google search")).toBe("google");
    expect(brandInText("hexagon")).toBeUndefined();
    expect(brandInText("cal.com bookings")).toBe("calcom");
  });
});

describe("modelBrand", () => {
  it("uses the provider, then the provider in the id, then the maker the id names", () => {
    expect(modelBrand({ provider: "Anthropic", id: "claude-opus-5-5" })).toBe("anthropic");
    expect(modelBrand({ provider: "AwsBedrock", id: "anthropic.claude" })).toBe("bedrock");
    expect(modelBrand({ id: "openai:gpt-5" })).toBe("openai");
    expect(modelBrand({ id: "openrouter/meta-llama/llama-4" })).toBe("openrouter");
    expect(modelBrand({ provider: "Agnostic", id: "claude-sonnet-5-5" })).toBe("anthropic");
    expect(modelBrand({ id: "qwen3:8b" })).toBe("qwen");
    expect(modelBrand({ provider: "Agnostic", id: "mock-precise" })).toBeUndefined();
  });
});

describe("the logo set", () => {
  it("has every logo the maps name", () => {
    for (const brand of Object.values(TOOLKIT_BRANDS)) expect(isBrandId(brand), brand).toBe(true);
    for (const id of BRAND_IDS) expect(BRAND_GLYPHS[id].paths.length).toBeGreaterThan(0);
  });

  it("maps only toolkits Agno has", () => {
    expect(toolkitList, SPEC).toBeDefined();
    const list = JSON.parse(readFileSync(toolkitList ?? "", "utf8")) as { toolkits: { key: string }[] };
    const keys = new Set(list.toolkits.map((toolkit) => toolkit.key));
    for (const key of Object.keys(TOOLKIT_BRANDS)) expect(keys.has(key), key).toBe(true);
  });
});
