// Service-account fixtures from the prototype's sample org: zendesk-bridge (per-agent run scopes, no expiry),
// ci-evals and slack-bot (an access role plus one scope), the AgentOS scope catalog, and stateful MSW handlers
// for list, detail, preview, create, issue/rotate, revoke and delete. Token values are built at runtime.
import type {
  CreatedOut,
  GatewayTokenOut,
  InstanceRefOut,
  IssuedTokenOut,
  NativeTokenOut,
  ScopeItemOut,
  ScopeOut,
  ServiceAccountDetailOut,
  ServiceAccountIn,
  ServiceAccountOut,
  ServiceAccountPreviewOut,
  TokenIn,
  TokenIssuedOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { ownerAccess, PROD, sampleInstances, sampleRoles, STAGING } from "./sample-org";

const NOW = Date.now();
const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const ahead = (ms: number) => new Date(NOW + ms).toISOString();

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
let tokenCounter = 0;

/** Four characters for a new token's display prefix. */
function shortId(): string {
  tokenCounter += 1;
  return Array.from(
    { length: 4 },
    (_, index) => ALPHABET[(tokenCounter * 11 + index * 5) % ALPHABET.length],
  ).join("");
}

/** A token-shaped value for tests: `prefix` and filler up to 32 characters after `agno_pat_`/`agn_pat_`. */
export function fakeToken(prefix: string): string {
  tokenCounter += 1;
  const head = prefix.startsWith("agn_pat_") ? "agn_pat_" : "agno_pat_";
  const filler = Array.from(
    { length: 32 - (prefix.length - head.length) },
    (_, index) => ALPHABET[(index * 7 + tokenCounter * 13) % ALPHABET.length],
  ).join("");
  return `${prefix}${filler}`;
}

const ref = (id: string): InstanceRefOut => {
  const found = sampleInstances.find((item) => item.id === id);
  return { id, slug: found?.slug ?? id, display_name: found?.display_name ?? id };
};

export const SA_CREATORS = {
  dana: { id: "usr_dana", name: "Dana Okafor" },
  sam: { id: "usr_sam", name: "Sam Rivera" },
  priya: { id: "usr_priya", name: "Priya Nair" },
} as const;

/** Write and delete scopes, `agent_os:admin` and any `service_accounts:*` need an explicit confirmation. */
export function isPrivilegedScope(scope: string): boolean {
  const parts = scope.split(":");
  return (
    scope === "agent_os:admin" ||
    parts[0] === "service_accounts" ||
    ["write", "delete"].includes(parts.at(-1) ?? "")
  );
}

function sourceLabel(source: "role" | "custom", roleName: string | null, extras: number): string {
  if (source === "custom" || roleName === null) return "Custom scopes";
  if (extras === 0) return `Access role: ${roleName}`;
  return `Access role: ${roleName} + ${String(extras)} scope${extras === 1 ? "" : "s"}`;
}

function nativeToken(
  fields: Partial<NativeTokenOut> & Pick<NativeTokenOut, "id" | "prefix">,
): NativeTokenOut {
  return {
    kind: "native",
    instance: ref(PROD),
    status: "active",
    scopes: [],
    created_at: ago(80 * DAY),
    revoked_at: null,
    expires_at: null,
    last_used_at: null,
    ...fields,
  };
}

const ROTATION_NOTE =
  "Rotate issues a new gateway token and keeps the old one valid for 24 h so callers can switch. AgentOS can't " +
  "rotate a native token: rotating revokes it and creates a new one under the same name, so callers see a brief gap.";

type Seed = {
  id: string;
  name: string;
  description: string;
  created_by: { id: string; name: string };
  created_at: string;
  role: { id: string; name: string; scopes: string[] } | null;
  scopes: string[];
  instances: string[];
  last_used_at: string | null;
  expires_at: string | null;
  forwards_user_id: boolean;
  kinds: ("native" | "gateway")[];
  isolation_note: string;
  native_tokens: NativeTokenOut[];
  gateway_tokens: GatewayTokenOut[];
};

function cliCommand(seed: {
  name: string;
  instances: string[];
  role: string | null;
  scopes: string[];
  expires_in: string;
  kinds: string[];
  forwards_user_id: boolean;
  privileged: boolean;
}): string {
  const lines = [`agnostic tokens create ${seed.name || "<name>"}`];
  lines.push(...seed.instances.map((slug) => `--instance ${slug}`));
  if (seed.role) {
    lines.push(`--role ${seed.role}`);
    if (seed.scopes.length) lines.push(`--extra-scopes ${seed.scopes.join(",")}`);
  } else if (seed.scopes.length) lines.push(`--scopes ${seed.scopes.join(",")}`);
  lines.push(`--expires-in ${seed.expires_in}`);
  lines.push(...seed.kinds.map((kind) => `--kind ${kind}`));
  if (seed.forwards_user_id) lines.push("--forwards-user-id");
  if (seed.privileged) lines.push("--yes-privileged");
  return lines.join(" \\\n  ");
}

function detailOf(seed: Seed): ServiceAccountDetailOut {
  const roleScopes = seed.role?.scopes ?? [];
  const all = [...new Set([...roleScopes, ...seed.scopes])];
  const items: ScopeItemOut[] = [
    ...roleScopes.map((scope) => ({
      scope,
      source: `role:${seed.role?.name ?? ""}`,
      privileged: isPrivilegedScope(scope),
    })),
    ...seed.scopes
      .filter((scope) => !roleScopes.includes(scope))
      .map((scope) => ({ scope, source: "custom", privileged: isPrivilegedScope(scope) })),
  ];
  const expires = seed.expires_at ? new Date(seed.expires_at).getTime() : null;
  const active = [...seed.native_tokens, ...seed.gateway_tokens].filter((token) => token.status === "active");
  return {
    id: seed.id,
    name: seed.name,
    principal: `sa:${seed.name}`,
    description: seed.description,
    created_by: seed.created_by,
    created_at: seed.created_at,
    forwards_user_id: seed.forwards_user_id,
    scope_source: seed.role ? "role" : "custom",
    role_id: seed.role?.id ?? null,
    role_name: seed.role?.name ?? null,
    source_label: sourceLabel(seed.role ? "role" : "custom", seed.role?.name ?? null, seed.scopes.length),
    scopes: all,
    extra_scopes: seed.role ? seed.scopes : [],
    scope_count: all.length,
    privileged: all.some(isPrivilegedScope),
    instances: seed.instances.map(ref),
    last_used_at: seed.last_used_at,
    expires_at: seed.expires_at,
    expired: expires !== null && expires < NOW,
    expiry_warning: expires === null || expires - NOW < 14 * DAY,
    kinds: seed.kinds,
    active_tokens: active.length,
    scope_items: items,
    isolation_note: seed.isolation_note,
    native_tokens: seed.native_tokens,
    gateway_tokens: seed.gateway_tokens,
    rotation_note: ROTATION_NOTE,
    cli_command: cliCommand({
      name: seed.name,
      instances: seed.instances.map((id) => ref(id).slug),
      role: seed.role?.id ?? null,
      scopes: seed.scopes,
      expires_in: "90d",
      kinds: seed.kinds,
      forwards_user_id: seed.forwards_user_id,
      privileged: all.some(isPrivilegedScope),
    }),
  };
}

function seeds(): Seed[] {
  return [
    {
      id: "sa_zendesk",
      name: "zendesk-bridge",
      description: "Forwards Zendesk tickets to the support agents and posts replies back.",
      created_by: SA_CREATORS.dana,
      created_at: ago(83 * DAY),
      role: null,
      scopes: [
        "agents:support-triage:run",
        "agents:billing-agent:run",
        "teams:escalation-team:run",
        "workflows:ticket-router:run",
        "sessions:read",
        "sessions:write",
      ],
      instances: [PROD],
      last_used_at: ago(2000),
      expires_at: null,
      forwards_user_id: true,
      kinds: ["native", "gateway"],
      isolation_note:
        "Sends user_id per request (zd:<ticket user>), so user isolation applies to each customer.",
      native_tokens: [
        nativeToken({
          id: "tok_7Hq2",
          prefix: "agno_pat_7Hq2",
          created_at: ago(83 * DAY),
          last_used_at: ago(2000),
        }),
        nativeToken({
          id: "tok_3Lw9",
          prefix: "agno_pat_3Lw9",
          status: "revoked",
          created_at: ago(200 * DAY),
          revoked_at: ago(83 * DAY),
          last_used_at: ago(83 * DAY),
        }),
      ],
      gateway_tokens: [
        {
          id: "gwt_Qm4x",
          kind: "gateway",
          prefix: "agn_pat_Qm4x",
          status: "active",
          created_at: ago(83 * DAY),
          grace_until: null,
          revoked_at: null,
          revoke_reason: null,
          last_used_at: ago(9 * MINUTE),
          last_used_ip: "10.0.4.12",
        },
      ],
    },
    {
      id: "sa_cievals",
      name: "ci-evals",
      description: "Runs eval suites from CI on every pull request to northwind/agent-platform.",
      created_by: SA_CREATORS.sam,
      created_at: ago(366 * DAY),
      role: null,
      scopes: ["agents:read", "agents:run", "evals:read", "evals:write"],
      instances: [STAGING],
      last_used_at: ago(120 * MINUTE),
      expires_at: ahead(88 * DAY),
      forwards_user_id: false,
      kinds: ["native"],
      isolation_note: "No user_id; eval runs are owned by sa:ci-evals.",
      native_tokens: [
        nativeToken({
          id: "tok_K2c8",
          prefix: "agno_pat_K2c8",
          instance: ref(STAGING),
          created_at: ago(366 * DAY),
          last_used_at: ago(120 * MINUTE),
          expires_at: ahead(88 * DAY),
        }),
      ],
      gateway_tokens: [],
    },
    {
      id: "sa_slackbot",
      name: "slack-bot",
      description: "Posts approval requests to Slack and answers questions with support-triage.",
      created_by: SA_CREATORS.priya,
      created_at: ago(51 * DAY),
      role: { id: "rol_viewer", name: "Viewer", scopes: ["agents:read", "agents:support-triage:run"] },
      scopes: ["approvals:read"],
      instances: [PROD],
      last_used_at: ago(9 * MINUTE),
      expires_at: ahead(10 * DAY),
      forwards_user_id: false,
      kinds: ["native"],
      isolation_note: "Can post approvals but not resolve them: scoped service accounts get 404 on resolve.",
      native_tokens: [
        nativeToken({
          id: "tok_Wp5n",
          prefix: "agno_pat_Wp5n",
          created_at: ago(51 * DAY),
          last_used_at: ago(9 * MINUTE),
          expires_at: ahead(10 * DAY),
        }),
      ],
      gateway_tokens: [],
    },
  ];
}

export function sampleServiceAccountDetails(): ServiceAccountDetailOut[] {
  return seeds().map(detailOf);
}

/** The list row of a detail (what `GET /service-accounts` returns). */
export function serviceAccountRow(detail: ServiceAccountDetailOut): ServiceAccountOut {
  return {
    id: detail.id,
    name: detail.name,
    principal: detail.principal,
    description: detail.description,
    created_by: detail.created_by,
    created_at: detail.created_at,
    forwards_user_id: detail.forwards_user_id,
    scope_source: detail.scope_source,
    role_id: detail.role_id,
    role_name: detail.role_name,
    source_label: detail.source_label,
    scopes: detail.scopes,
    extra_scopes: detail.extra_scopes,
    scope_count: detail.scope_count,
    privileged: detail.privileged,
    instances: detail.instances,
    last_used_at: detail.last_used_at,
    expires_at: detail.expires_at,
    expired: detail.expired,
    expiry_warning: detail.expiry_warning,
    kinds: detail.kinds,
    active_tokens: detail.active_tokens,
  };
}

function catalogEntry(family: string, action: string, description: string, hidden = false): ScopeOut {
  const scope = `${family}:${action}`;
  return {
    scope,
    family,
    action,
    description,
    source: "agentos",
    resource_kind: ["agents", "teams", "workflows"].includes(family) ? "per_component" : "global",
    privileged: isPrivilegedScope(scope),
    hidden,
    agentos_min_version: "3.1.0",
  };
}

/** A slice of the AgentOS scope catalog (`GET /access/scopes`), with a hidden family and a control-plane scope. */
export const sampleScopeCatalog: ScopeOut[] = [
  catalogEntry("agents", "read", "See agents"),
  catalogEntry("agents", "run", "Run agents"),
  catalogEntry("agents", "write", "Create and change agents"),
  catalogEntry("teams", "read", "See agent teams"),
  catalogEntry("teams", "run", "Run agent teams"),
  catalogEntry("sessions", "read", "See sessions"),
  catalogEntry("sessions", "write", "Create and change sessions"),
  catalogEntry("metrics", "read", "See metrics"),
  catalogEntry("evals", "read", "See evaluation runs"),
  catalogEntry("approvals", "read", "See approvals"),
  catalogEntry("service_accounts", "write", "Create and change native service accounts"),
  catalogEntry("wiki", "read", "See the Company wiki", true),
  {
    ...catalogEntry("service_accounts", "manage", "Manage org service accounts"),
    source: "control_plane",
  },
];

type Store = { accounts: ServiceAccountDetailOut[] };

const problem = (status: number, code: string, title: string, extra: Record<string, unknown> = {}) =>
  HttpResponse.json(
    { type: "about:blank", status, code, title, detail: title, ...extra },
    { status, headers: { "content-type": "application/problem+json" } },
  );

function expiryOf(choice: string | undefined): string | null {
  const days = { "30d": 30, "90d": 90, "365d": 365, never: null }[choice ?? "90d"] ?? null;
  return days === null ? null : ahead(days * DAY);
}

function previewOf(body: ServiceAccountIn): ServiceAccountPreviewOut {
  const role = sampleRoles.find((item) => item.id === body.role_id || item.slug === body.role_id);
  const scopes = body.scopes ?? [];
  const all = [...new Set([...(role?.scopes ?? []), ...scopes])];
  const privileged = all.filter(isPrivilegedScope).sort();
  const problems: string[] = [];
  if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(body.name.trim()))
    problems.push("Use lowercase letters, digits and dashes, starting and ending with a letter or digit.");
  const slugs = body.instances.map(
    (id) => sampleInstances.find((item) => item.id === id || item.slug === id)?.slug ?? id,
  );
  return {
    principal: `sa:${body.name.trim()}`,
    privileged_scopes: privileged,
    expires_at: expiryOf(body.expires_in),
    problems,
    token_prefixes: {},
    cli_command: cliCommand({
      name: body.name.trim(),
      instances: slugs,
      role: role?.slug ?? body.role_id ?? null,
      scopes,
      expires_in: body.expires_in ?? "90d",
      kinds: body.kinds ?? ["native"],
      forwards_user_id: body.forwards_user_id ?? false,
      privileged: privileged.length > 0,
    }),
  };
}

function issue(
  detail: ServiceAccountDetailOut,
  kind: "native" | "gateway",
  instance: InstanceRefOut | null,
): IssuedTokenOut {
  const short = shortId();
  const prefix = kind === "native" ? `agno_pat_${short}` : `agn_pat_${short}`;
  const host = instance
    ? (sampleInstances.find((item) => item.id === instance.id)?.endpoint_url ?? "")
    : "http://agnostic.test/api/v1/instances/prod-agentos/os";
  return {
    id: `tok_${short}`,
    kind,
    token: fakeToken(prefix),
    prefix,
    instance,
    expires_at: detail.expires_at,
    curl:
      `curl -X POST ${host}/agents/support-triage/runs \\\n` +
      `  -H "Authorization: Bearer $AGNO_PAT" \\\n` +
      `  -F message="Hello from a service account"`,
  };
}

function withActiveCount(detail: ServiceAccountDetailOut): ServiceAccountDetailOut {
  const active = [...detail.native_tokens, ...detail.gateway_tokens].filter(
    (token) => token.status === "active",
  );
  return { ...detail, active_tokens: active.length };
}

/** `sa:<name>`, a name or an id → the account. */
function find(store: Store, key: string): ServiceAccountDetailOut | undefined {
  const name = key.replace(/^sa:/, "");
  return store.accounts.find((item) => item.id === key || item.name === name);
}

/** Org access of an Owner who also manages service accounts. */
export const serviceAccountsManagerAccess = {
  ...ownerAccess,
  control_plane_scopes: [...ownerAccess.control_plane_scopes, "service_accounts:manage"],
};

export function serviceAccountsHandlers() {
  const store: Store = { accounts: sampleServiceAccountDetails() };
  return [
    http.get(`${API}/me/access`, ({ request }) => {
      if (new URL(request.url).searchParams.get("instance")) return undefined;
      return HttpResponse.json(serviceAccountsManagerAccess);
    }),
    http.get(`${API}/access/scopes`, () => HttpResponse.json(sampleScopeCatalog)),
    http.get(`${API}/service-accounts`, () => HttpResponse.json(store.accounts.map(serviceAccountRow))),
    http.post(`${API}/service-accounts/preview`, async ({ request }) =>
      HttpResponse.json(previewOf((await request.json()) as ServiceAccountIn)),
    ),
    http.post(`${API}/service-accounts`, async ({ request }) => {
      const body = (await request.json()) as ServiceAccountIn;
      const preview = previewOf(body);
      if (preview.problems.length) return problem(422, "validation_failed", preview.problems[0] ?? "");
      if (store.accounts.some((item) => item.name === body.name))
        return problem(409, "conflict", `sa:${body.name} already exists.`);
      if (preview.privileged_scopes.length && !body.confirm_privileged)
        return problem(
          422,
          "privileged_confirmation_required",
          "Privileged scopes need an explicit confirmation",
          {
            privileged_scopes: preview.privileged_scopes,
          },
        );
      const role = sampleRoles.find((item) => item.id === body.role_id);
      const kinds = body.kinds ?? ["native"];
      const instances = body.instances.map(ref);
      const base = detailOf({
        id: `sa_${body.name.replace(/-/g, "")}`,
        name: body.name,
        description: body.description ?? "",
        created_by: SA_CREATORS.dana,
        created_at: new Date(NOW).toISOString(),
        role: role ? { id: role.id, name: role.name, scopes: role.scopes } : null,
        scopes: body.scopes ?? [],
        instances: body.instances,
        last_used_at: null,
        expires_at: expiryOf(body.expires_in),
        forwards_user_id: body.forwards_user_id ?? false,
        kinds,
        isolation_note: `No user_id: runs are owned by sa:${body.name}.`,
        native_tokens: [],
        gateway_tokens: [],
      });
      const tokens: IssuedTokenOut[] = [
        ...(kinds.includes("native") ? instances.map((instance) => issue(base, "native", instance)) : []),
        ...(kinds.includes("gateway") ? [issue(base, "gateway", null)] : []),
      ];
      const account = withActiveCount({
        ...base,
        native_tokens: tokens
          .filter((token) => token.kind === "native")
          .map((token) =>
            nativeToken({
              id: token.id,
              prefix: token.prefix,
              instance: token.instance,
              created_at: new Date(NOW).toISOString(),
              expires_at: token.expires_at,
            }),
          ),
        gateway_tokens: tokens
          .filter((token) => token.kind === "gateway")
          .map((token) => ({
            id: token.id,
            kind: "gateway",
            prefix: token.prefix,
            status: "active",
            created_at: new Date(NOW).toISOString(),
            grace_until: null,
            revoked_at: null,
            revoke_reason: null,
            last_used_at: null,
            last_used_ip: null,
          })),
      });
      store.accounts.push(account);
      const created: CreatedOut = { account, tokens };
      return HttpResponse.json(created, { status: 201 });
    }),
    http.get(`${API}/service-accounts/:account`, ({ params }) => {
      const found = find(store, String(params.account));
      return found ? HttpResponse.json(found) : problem(404, "not_found", "No such service account");
    }),
    http.delete(`${API}/service-accounts/:account`, ({ params }) => {
      const found = find(store, String(params.account));
      if (!found) return problem(404, "not_found", "No such service account");
      store.accounts = store.accounts.filter((item) => item !== found);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(`${API}/service-accounts/:account/tokens`, async ({ params, request }) => {
      const found = find(store, String(params.account));
      if (!found) return problem(404, "not_found", "No such service account");
      const body = (await request.json()) as TokenIn;
      const at = new Date().toISOString();
      let next: ServiceAccountDetailOut;
      let replaced: string | null = null;
      let graceUntil: string | null = null;
      let token: IssuedTokenOut;
      if (body.kind === "gateway") {
        token = issue(found, "gateway", null);
        const current = found.gateway_tokens.find((item) => item.status === "active" && !item.grace_until);
        replaced = current?.id ?? null;
        graceUntil = current ? new Date(Date.now() + DAY).toISOString() : null;
        next = {
          ...found,
          gateway_tokens: [
            ...found.gateway_tokens.map((item) =>
              item === current ? { ...item, grace_until: graceUntil, revoke_reason: "rotated" } : item,
            ),
            {
              id: token.id,
              kind: "gateway",
              prefix: token.prefix,
              status: "active",
              created_at: at,
              grace_until: null,
              revoked_at: null,
              revoke_reason: null,
              last_used_at: null,
              last_used_ip: null,
            },
          ],
        };
      } else {
        const instance =
          found.instances.find((item) => item.id === body.instance || item.slug === body.instance) ??
          (found.instances.length === 1 ? found.instances[0] : undefined);
        if (!instance)
          return problem(422, "validation_failed", "Say which instance the native token is for.");
        token = issue(found, "native", instance);
        const current = found.native_tokens.find(
          (item) => item.status === "active" && item.instance?.id === instance.id,
        );
        replaced = current?.id ?? null;
        next = {
          ...found,
          native_tokens: [
            ...found.native_tokens.map((item) =>
              item === current ? { ...item, status: "revoked" as const, revoked_at: at } : item,
            ),
            nativeToken({ id: token.id, prefix: token.prefix, instance, created_at: at }),
          ],
        };
      }
      next = withActiveCount(next);
      store.accounts = store.accounts.map((item) => (item === found ? next : item));
      const issued: TokenIssuedOut = { account: next, token, replaced_id: replaced, grace_until: graceUntil };
      return HttpResponse.json(issued, { status: 201 });
    }),
    http.delete(`${API}/service-accounts/:account/tokens/:token`, ({ params }) => {
      const found = find(store, String(params.account));
      if (!found) return problem(404, "not_found", "No such service account");
      const id = String(params.token);
      const at = new Date().toISOString();
      const next = withActiveCount({
        ...found,
        native_tokens: found.native_tokens.map((item) =>
          item.id === id ? { ...item, status: "revoked" as const, revoked_at: at } : item,
        ),
        gateway_tokens: found.gateway_tokens.map((item) =>
          item.id === id
            ? { ...item, status: "revoked" as const, revoked_at: at, revoke_reason: "revoked" }
            : item,
        ),
      });
      store.accounts = store.accounts.map((item) => (item === found ? next : item));
      return HttpResponse.json(next);
    }),
  ];
}
