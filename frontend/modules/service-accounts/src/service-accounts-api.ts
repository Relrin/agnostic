// URL state, wording and small rules shared by the service-accounts table, its detail aside and the create sheet.
import {
  isProblem,
  type InstanceOut,
  type InstanceRefOut,
  type ScopeOut,
  type ServiceAccountIn,
  type ServiceAccountOut,
} from "@agnostic/api";
import { toDate } from "@agnostic/core";
import type { QueryClient } from "@tanstack/react-query";

export type Expiry = NonNullable<ServiceAccountIn["expires_in"]>;
export type TokenKind = "native" | "gateway";

const DAY = 24 * 3600 * 1000;

export const EXPIRY_OPTIONS: readonly { value: Expiry; label: string; days: number | null }[] = [
  { value: "90d", label: "In 90 days", days: 90 },
  { value: "30d", label: "In 30 days", days: 30 },
  { value: "365d", label: "In 1 year", days: 365 },
  { value: "never", label: "Never", days: null },
];

export const KIND_LABELS: Record<TokenKind, string> = { native: "Native", gateway: "Gateway" };

export const KIND_HINTS: Record<TokenKind, string> = {
  native:
    "An agno_pat_ token on each selected instance, called directly against AgentOS. One per instance; scopes live in the instance's database.",
  gateway:
    "One agn_pat_ token for the Agnostic gateway, valid on every selected instance. Rotation keeps the old token valid for 24 h.",
};

/** `?account=<name>`: the account open in the aside. */
export function readAccount(search: Record<string, unknown>): string | undefined {
  const value = search.account;
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/** List and every open detail, after a change. */
export async function refreshAccounts(client: QueryClient): Promise<void> {
  await Promise.all(
    ["serviceAccountsListAccounts", "serviceAccountsGetAccount"].map((id) =>
      client.invalidateQueries({ queryKey: [{ _id: id }] }),
    ),
  );
}

/** "30 Jan 2027". */
export function formatDate(value: string | Date | null | undefined): string {
  const date = value instanceof Date ? value : toDate(value);
  if (!date) return "—";
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** The expiry date a choice gives, from now. */
export function expiryDate(choice: Expiry, now: Date = new Date()): Date | undefined {
  const days = EXPIRY_OPTIONS.find((option) => option.value === choice)?.days;
  return days ? new Date(now.getTime() + days * DAY) : undefined;
}

export type ExpiryTone = "danger" | "warning" | "normal";

/** The Expires cell: red when expired, amber with no expiry or under two weeks left. */
export function expiryState(row: Pick<ServiceAccountOut, "expires_at" | "expired" | "expiry_warning">): {
  text: string;
  tone: ExpiryTone;
} {
  if (row.expired) return { text: `Expired ${formatDate(row.expires_at)}`, tone: "danger" };
  if (!row.expires_at) return { text: "No expiry", tone: "warning" };
  return { text: formatDate(row.expires_at), tone: row.expiry_warning ? "warning" : "normal" };
}

/** Same rule as the server: write and delete scopes, `agent_os:admin` and any `service_accounts:*`. */
export function isPrivileged(scope: string): boolean {
  const parts = scope.split(":");
  return (
    scope === "agent_os:admin" ||
    parts[0] === "service_accounts" ||
    parts.at(-1) === "write" ||
    parts.at(-1) === "delete"
  );
}

/** `agents:support-triage:run`: one component's scope, typed by hand. */
export const PER_COMPONENT_SCOPE =
  /^(agents|teams|workflows):[A-Za-z0-9][A-Za-z0-9._-]*:(read|run|write|delete)$/;

/** The AgentOS scopes a service account can hold, grouped by family in catalog order. */
export function scopeFamilies(catalog: readonly ScopeOut[]): { family: string; scopes: ScopeOut[] }[] {
  const families = new Map<string, ScopeOut[]>();
  for (const scope of catalog) {
    if (scope.hidden || scope.source !== "agentos") continue;
    const list = families.get(scope.family) ?? [];
    list.push(scope);
    families.set(scope.family, list);
  }
  return [...families].map(([family, scopes]) => ({ family, scopes }));
}

/** The privileged scopes a 422 `privileged_confirmation_required` lists. */
export function privilegedFromError(error: unknown): string[] | undefined {
  if (!isProblem(error) || error.code !== "privileged_confirmation_required") return undefined;
  const scopes = (error as { privileged_scopes?: unknown }).privileged_scopes;
  return Array.isArray(scopes) ? scopes.filter((item): item is string => typeof item === "string") : [];
}

export type EnvTag = InstanceOut["env_tag"];

/** The environment of an instance the account applies on (the ref carries no tag). */
export function envOf(
  instances: readonly InstanceOut[] | undefined,
  ref: InstanceRefOut,
): EnvTag | undefined {
  return instances?.find((instance) => instance.id === ref.id)?.env_tag;
}
