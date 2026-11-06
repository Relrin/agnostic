// Wording and small rules shared by the tool catalog page and its entry editor.
import type { EntryOut, ToolkitParamOut } from "@agnostic/api";
import type { BadgeProps } from "@agnostic/ui";
import type { QueryClient } from "@tanstack/react-query";

export type Level = EntryOut["level"];
export type Kind = EntryOut["kind"];
export type Transport = NonNullable<EntryOut["transport"]>;

export const LEVELS: readonly { value: Level; label: string; hint: string }[] = [
  {
    value: "org",
    label: "Organization",
    hint: "Offered to everyone. Org owners and administrators manage these.",
  },
  { value: "team", label: "Team", hint: "Offered to one group's members. The group's owners manage these." },
  {
    value: "custom",
    label: "Custom",
    hint: "Set up by a builder for one instance, from the full Agno toolkit list.",
  },
];

export const LEVEL_TONE: Record<Level, NonNullable<BadgeProps["tone"]>> = {
  org: "success",
  team: "info",
  custom: "outline",
};

export const TRANSPORTS: readonly { value: Transport; label: string; hint: string }[] = [
  { value: "streamable-http", label: "Streamable HTTP", hint: "A remote server: the usual choice." },
  { value: "sse", label: "SSE", hint: "Older remote servers (deprecated in the MCP spec)." },
  { value: "stdio", label: "stdio", hint: "A command the runtime starts. Owners and administrators only." },
];

export const STATE_TEXT: Record<string, { text: string; tone: NonNullable<BadgeProps["tone"]> }> = {
  connected: { text: "connected", tone: "success" },
  pending: { text: "connecting", tone: "warning" },
  failed: { text: "not connected", tone: "danger" },
  missing_env: { text: "missing credential", tone: "danger" },
  stdio_disabled: { text: "not allowed here", tone: "danger" },
  conflict: { text: "name taken", tone: "danger" },
};

/** `{"env": "NAME"}`: how a credential is stored (the runtime reads the variable; no value leaves it). */
export type EnvRef = { env: string; format?: string };

export function isEnvRef(value: unknown): value is EnvRef {
  return typeof value === "object" && value !== null && typeof (value as { env?: unknown }).env === "string";
}

export function kindLabel(entry: Pick<EntryOut, "kind" | "transport" | "toolkit_key">): string {
  if (entry.kind === "toolkit") return `Agno toolkit · ${entry.toolkit_key ?? "?"}`;
  return `MCP server · ${entry.transport ?? "?"}`;
}

/** Lowercase letters, digits and single hyphens, starting with a letter. */
export function slugOf(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^[^a-z]+/, "")
      .replace(/-+$/g, "")
      .slice(0, 40) || "tool"
  );
}

/** A form value as the API wants it for a toolkit parameter. */
export function paramValue(
  param: ToolkitParamOut,
  raw: string | boolean | undefined,
  /** The parameter already came from an environment variable: it stays one. */
  fromEnv = false,
): unknown {
  if (raw === undefined || raw === "") return undefined;
  if (param.secret || fromEnv) return { env: String(raw) };
  switch (param.type) {
    case "bool":
      return Boolean(raw);
    case "int":
    case "float": {
      // Not a number: send it as typed, so the check says what's wrong instead of the value silently vanishing.
      const number = param.type === "int" ? Number.parseInt(String(raw), 10) : Number.parseFloat(String(raw));
      return Number.isNaN(number) ? String(raw) : number;
    }
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

/** A stored parameter back into the form. */
export function formValue(value: unknown): string | boolean | undefined {
  if (value === undefined || value === null) return undefined;
  if (isEnvRef(value)) return value.env;
  if (typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

export function listText(value: unknown): string {
  return Array.isArray(value) ? value.map(String).join(", ") : "";
}

export function textList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** Every list and open entry, after a change. */
export async function refreshCatalog(client: QueryClient): Promise<void> {
  await Promise.all(
    ["toolCatalogListEntries", "toolCatalogGetEntry", "studioRegistry"].map((id) =>
      client.invalidateQueries({ queryKey: [{ _id: id }] }),
    ),
  );
}
