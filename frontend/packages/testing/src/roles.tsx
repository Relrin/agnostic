// Roles & permissions fixtures from the prototype's sample org: the scope catalog, built-in roles with their
// permission matrices (Operator held by 9 people and 2 groups), a custom role still bound, versions; plus stateful
// MSW handlers that preview, save (with version conflicts), reset, duplicate and delete roles.
import type {
  BindingOut,
  ReachOut,
  RoleIn,
  RoleOut,
  RolePreviewOut,
  RoleUpdate,
  RoleVersionOut,
  ScopeOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { DANIEL, MARCUS, PROD, STAGING, ownerAccess, sampleMembers, sampleRoles } from "./sample-org";

const T = "2026-11-01T09:00:00Z";
const PER_COMPONENT = new Set(["agents", "teams", "workflows"]);
export const SUPPORT_AI_GROUP = "grp_01M6A0EEZEQ373S26F2014SAI";
export const BILLING_OPS_GROUP = "grp_01M6A0EEZEQ373S26F2014BIL";
export const SUPPORT_LEAD_ROLE = "rol_01M6A0EEZEQ373S26F2014SUP";

function agentos(family: string, actions: string[], label: string, hidden = false): ScopeOut[] {
  const verbs: Record<string, string> = {
    read: "See",
    write: "Create and change",
    delete: "Delete",
    run: "Run",
  };
  return actions.map((action) => ({
    scope: `${family}:${action}`,
    family,
    action,
    source: "agentos",
    description: `${verbs[action] ?? action} ${label}`,
    resource_kind: PER_COMPONENT.has(family) ? "per_component" : "global",
    privileged: action === "write" || action === "delete",
    agentos_min_version: "3.1.0",
    hidden,
  }));
}

function controlPlane(scope: string, description: string): ScopeOut {
  const cut = scope.lastIndexOf(":");
  return {
    scope,
    family: scope.slice(0, cut),
    action: scope.slice(cut + 1),
    source: "control_plane",
    description,
    resource_kind: "global",
    privileged: false,
    agentos_min_version: null,
    hidden: false,
  };
}

/** `GET /access/scopes`: AgentOS 3.1 scopes and the control-plane scopes modules declare. */
export const rolesCatalog: ScopeOut[] = [
  {
    scope: "agent_os:admin",
    family: "agent_os",
    action: "admin",
    source: "agentos",
    description: "Everything on the instance, past user isolation",
    resource_kind: "global",
    privileged: true,
    agentos_min_version: null,
    hidden: false,
  },
  ...agentos("config", ["read", "write"], "the OS configuration (write: database migrations)"),
  ...agentos("registry", ["read"], "the code-defined registry"),
  ...agentos("filesystem", ["read"], "agent file systems"),
  ...agentos("components", ["read", "write", "delete"], "Studio components and versions"),
  ...agentos("agents", ["read", "run", "write", "delete"], "agents"),
  ...agentos("teams", ["read", "run", "write", "delete"], "agent teams"),
  ...agentos("workflows", ["read", "run", "write", "delete"], "workflows"),
  ...agentos("sessions", ["read", "write", "delete"], "sessions"),
  ...agentos("memories", ["read", "write", "delete"], "memories"),
  ...agentos("learnings", ["read", "write", "delete"], "learnings"),
  ...agentos("knowledge", ["read", "write", "delete"], "knowledge"),
  ...agentos("traces", ["read"], "traces"),
  ...agentos("metrics", ["read", "write"], "metrics (write: refresh)"),
  ...agentos("evals", ["read", "write", "delete"], "evaluation runs"),
  ...agentos("schedules", ["read", "write", "delete"], "schedules"),
  ...agentos("approvals", ["read", "write", "delete"], "approvals"),
  ...agentos("service_accounts", ["read", "write", "delete"], "native service accounts"),
  ...agentos("products", ["read", "write", "delete"], "Company products", true),
  controlPlane("audit:read", "Read the audit log"),
  controlPlane("audit:export", "Export the audit log"),
  controlPlane("org:read", "See the org"),
  controlPlane("org:roles:write", "Change roles and bindings"),
  controlPlane("os:delete", "Delete an instance record"),
  controlPlane("queue:operate", "Requeue and resume queued runs"),
  controlPlane("service_accounts:manage", "Manage org service accounts"),
  controlPlane("evals:gates:write", "Change publish gates"),
];

const R = ["read"];
const RW = ["read", "write"];
const RWD = ["read", "write", "delete"];

/** Built-in defaults (what Reset to default restores). */
const DEFAULTS: Record<string, Pick<RoleOut, "name" | "description" | "color" | "permissions">> = {
  "instance-admin": {
    name: "Instance admin",
    description: "Everything on the instance, including other people's sessions and the queue.",
    color: "#C5F25C",
    permissions: { agent_os: ["admin"], queue: ["operate"] },
  },
  operator: {
    name: "Operator",
    description: "Runs and supervises live agents. Can resolve approvals; can't change definitions.",
    color: "#C5F25C",
    permissions: {
      agents: ["read", "run"],
      teams: ["read", "run"],
      workflows: ["read", "run"],
      components: R,
      registry: R,
      sessions: R,
      memories: R,
      learnings: R,
      knowledge: R,
      traces: R,
      metrics: R,
      evals: R,
      approvals: RWD,
      schedules: RW,
      config: R,
      queue: ["operate"],
    },
  },
  builder: {
    name: "Builder",
    description: "Builds and tests agents, teams and workflows in Studio; manages knowledge and evaluations.",
    color: "#7DA6FF",
    permissions: {
      agents: ["read", "run", "write"],
      teams: ["read", "run", "write"],
      workflows: ["read", "run", "write"],
      components: RWD,
      registry: R,
      sessions: RW,
      knowledge: RWD,
      traces: R,
      evals: RWD,
      config: R,
    },
  },
  viewer: {
    name: "Viewer",
    description: "Read-only: sees agents, runs, traces, metrics and context, changes nothing.",
    color: "#A9AFB8",
    permissions: Object.fromEntries(
      ["agents", "teams", "workflows", "sessions", "knowledge", "traces", "metrics", "approvals"].map(
        (family) => [family, R],
      ),
    ),
  },
};

/** The token scopes a role's matrix and run scope produce (selected components replace `<resource>:run`). */
export function roleScopes(
  permissions: Record<string, string[]>,
  runScope: Record<string, string[] | "all"> = {},
): string[] {
  const out = new Set<string>();
  for (const [resource, actions] of Object.entries(permissions)) {
    for (const action of actions) {
      const selected = runScope[resource] ?? "all";
      if (action === "run" && selected !== "all") for (const id of selected) out.add(`${resource}:${id}:run`);
      else out.add(`${resource}:${action}`);
    }
  }
  return [...out].sort();
}

function withScopes(role: RoleOut): RoleOut {
  return { ...role, scopes: roleScopes(role.permissions, role.run_scope) };
}

const COUNTS: Record<string, Pick<RoleOut, "people" | "groups" | "service_accounts" | "version">> = {
  "instance-admin": { people: 2, groups: 0, service_accounts: 0, version: 1 },
  operator: { people: 9, groups: 2, service_accounts: 1, version: 4 },
  builder: { people: 7, groups: 1, service_accounts: 0, version: 2 },
  viewer: { people: 6, groups: 0, service_accounts: 0, version: 3 },
};

/** `GET /access/roles`: the sample org's built-ins with their matrices (Viewer was edited: it can also write knowledge). */
export const rolesSampleRoles: RoleOut[] = [
  ...sampleRoles.map((role) => {
    const defaults = DEFAULTS[role.slug];
    const permissions = defaults?.permissions ?? {};
    return withScopes({
      ...role,
      ...defaults,
      ...COUNTS[role.slug],
      permissions: role.slug === "viewer" ? { ...permissions, knowledge: RW } : permissions,
      bindable_instance_ids: null,
      run_scope: {},
    });
  }),
  withScopes({
    id: SUPPORT_LEAD_ROLE,
    slug: "support-lead",
    name: "Support lead",
    description: "Operator plus knowledge edits for the support team.",
    color: "#B79CFF",
    kind: "custom",
    permissions: { agents: ["read", "run"], sessions: R, knowledge: RW, approvals: RW },
    run_scope: { agents: ["support-triage", "billing-agent"] },
    bindable_instance_ids: [PROD],
    scopes: [],
    people: 3,
    groups: 1,
    service_accounts: 0,
    version: 1,
  }),
];

function binding(id: string, fields: Partial<BindingOut> & Pick<BindingOut, "principal_id">): BindingOut {
  return {
    id,
    principal_kind: "user",
    instance_id: PROD,
    role_id: "rol_operator",
    scopes: [],
    expires_at: null,
    reason: null,
    created_by: DANIEL,
    created_at: T,
    ...fields,
  };
}

const BINDINGS: BindingOut[] = [
  binding("bnd_01M6A0EEZEQ373S26F20142B01", { principal_id: MARCUS }),
  binding("bnd_01M6A0EEZEQ373S26F20142B02", {
    principal_kind: "group",
    principal_id: SUPPORT_AI_GROUP,
    instance_id: null,
  }),
  binding("bnd_01M6A0EEZEQ373S26F20142B03", {
    principal_kind: "group",
    principal_id: BILLING_OPS_GROUP,
    instance_id: STAGING,
  }),
  binding("bnd_01M6A0EEZEQ373S26F20142B04", { principal_id: MARCUS, role_id: SUPPORT_LEAD_ROLE }),
  binding("bnd_01M6A0EEZEQ373S26F20142B05", {
    principal_kind: "group",
    principal_id: SUPPORT_AI_GROUP,
    role_id: SUPPORT_LEAD_ROLE,
  }),
];

const GROUP_NAMES: Record<string, string> = {
  [SUPPORT_AI_GROUP]: "Support AI",
  [BILLING_OPS_GROUP]: "Billing ops",
};

function reachOf(role: RoleOut): ReachOut {
  const bound = BINDINGS.filter((item) => item.role_id === role.id);
  const groups = [
    ...new Set(bound.filter((item) => item.principal_kind === "group").map((item) => item.principal_id)),
  ].map((id) => ({ id, name: GROUP_NAMES[id] ?? id }));
  const people = role.people;
  const parts = [`${String(people)} ${people === 1 ? "person" : "people"}`];
  if (groups.length)
    parts.push(
      `${String(groups.length)} group${groups.length === 1 ? "" : "s"} (${groups.map((group) => group.name).join(", ")})`,
    );
  return {
    people,
    direct_people: bound.filter((item) => item.principal_kind === "user").map((item) => item.principal_id),
    groups,
    service_accounts: [],
    sentence: parts.join(" and "),
  };
}

function problem(status: number, code: string, detail: string, extra: Record<string, unknown> = {}) {
  return HttpResponse.json(
    { type: `https://agnostic.dev/problems/${code}`, title: code, status, code, detail, ...extra },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

function versionsOf(role: RoleOut): RoleVersionOut[] {
  const out: RoleVersionOut[] = [];
  for (let version = role.version; version >= 1; version -= 1) {
    const drop = role.version - version;
    out.push({
      version,
      name: role.name,
      scopes: role.scopes.slice(0, Math.max(1, role.scopes.length - drop)),
      changed_by: DANIEL,
      changed_by_name: sampleMembers[0]?.display_name ?? "Daniel Okafor",
      changed_at: new Date(Date.parse(T) - drop * 86_400_000).toISOString(),
    });
  }
  return out;
}

/** What the handlers saw (request bodies), for assertions. */
export type RolesRecord = {
  previews: RoleIn[];
  updates: RoleUpdate[];
  resets: string[];
  deletes: string[];
  creates: RoleIn[];
};

/**
 * Stateful handlers over a fresh copy of the sample roles; pass `record` to see what the page sent. The `/me/access`
 * override adds `org:roles:delete` to the owner's control-plane scopes.
 */
export function rolesHandlers(record?: RolesRecord) {
  let roles = JSON.parse(JSON.stringify(rolesSampleRoles)) as RoleOut[];
  const find = (id: string) => roles.find((role) => role.id === id || role.slug === id);
  const apply = (role: RoleOut, body: RoleIn): RoleOut =>
    withScopes({
      ...role,
      name: body.name,
      description: body.description ?? role.description,
      color: body.color ?? role.color,
      permissions: body.permissions,
      run_scope: body.run_scope ?? {},
      bindable_instance_ids: body.bindable_instance_ids ?? null,
    });
  const previewOf = (before: RoleOut, after: RoleOut): RolePreviewOut => {
    const added = after.scopes.filter((scope) => !before.scopes.includes(scope));
    const removed = before.scopes.filter((scope) => !after.scopes.includes(scope));
    return {
      role: after,
      added,
      removed,
      lines: [
        ...added.map((text) => ({ op: "add" as const, text })),
        ...removed.map((text) => ({ op: "remove" as const, text })),
      ],
      reach: reachOf(before),
      warnings: [],
      redeploy: false,
    };
  };
  const invalid = (body: RoleIn) =>
    Object.values(body.permissions).every((actions) => actions.length === 0)
      ? "A role needs at least one permission."
      : undefined;

  return [
    http.get(`${API}/me/access`, ({ request }) => {
      if (new URL(request.url).searchParams.get("instance")) return undefined;
      return HttpResponse.json({
        ...ownerAccess,
        control_plane_scopes: [...ownerAccess.control_plane_scopes, "org:roles:delete"],
      });
    }),
    http.get(`${API}/access/scopes`, () => HttpResponse.json(rolesCatalog)),
    http.get(`${API}/access/roles`, () => HttpResponse.json(roles)),
    http.post(`${API}/access/roles`, async ({ request }) => {
      const body = (await request.json()) as RoleIn;
      record?.creates.push(body);
      const error = invalid(body);
      if (error) return problem(422, "validation_failed", error);
      const slug = body.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      const role = apply(
        {
          id: `rol_new_${slug}`,
          slug,
          name: body.name,
          description: "",
          color: "#C5F25C",
          kind: "custom",
          permissions: {},
          run_scope: {},
          bindable_instance_ids: null,
          scopes: [],
          people: 0,
          groups: 0,
          service_accounts: 0,
          version: 1,
        },
        body,
      );
      roles = [...roles, role];
      return HttpResponse.json(role, { status: 201 });
    }),
    http.get(`${API}/access/roles/:role`, ({ params }) => {
      const role = find(String(params.role));
      return role ? HttpResponse.json(role) : problem(404, "not_found", "There is no such access role.");
    }),
    http.patch(`${API}/access/roles/:role`, async ({ params, request }) => {
      const role = find(String(params.role));
      if (!role) return problem(404, "not_found", "There is no such access role.");
      const body = (await request.json()) as RoleUpdate;
      record?.updates.push(body);
      if (body.version !== role.version)
        return problem(
          409,
          "version_conflict",
          `${role.name} changed since you opened it (version ${String(role.version)}); reload to see the changes.`,
        );
      const error = invalid(body);
      if (error) return problem(422, "validation_failed", error);
      const after = { ...apply(role, body), version: role.version + 1 };
      roles = roles.map((item) => (item.id === role.id ? after : item));
      return HttpResponse.json(previewOf(role, after));
    }),
    http.post(`${API}/access/roles/:role/preview`, async ({ params, request }) => {
      const role = find(String(params.role));
      if (!role) return problem(404, "not_found", "There is no such access role.");
      const body = (await request.json()) as RoleIn;
      record?.previews.push(body);
      const error = invalid(body);
      if (error) return problem(422, "validation_failed", error);
      return HttpResponse.json(previewOf(role, apply(role, body)));
    }),
    http.post(`${API}/access/roles/:role/reset`, ({ params }) => {
      const role = find(String(params.role));
      if (!role) return problem(404, "not_found", "There is no such access role.");
      record?.resets.push(role.id);
      const defaults = DEFAULTS[role.slug];
      if (role.kind !== "built_in" || !defaults)
        return problem(422, "validation_failed", "Only built-in roles can be reset to their defaults.");
      const after = withScopes({
        ...role,
        ...defaults,
        run_scope: {},
        bindable_instance_ids: null,
        version: role.version + 1,
      });
      roles = roles.map((item) => (item.id === role.id ? after : item));
      return HttpResponse.json(previewOf(role, after));
    }),
    http.post(`${API}/access/roles/:role/duplicate`, async ({ params, request }) => {
      const role = find(String(params.role));
      if (!role) return problem(404, "not_found", "There is no such access role.");
      const body = (await request.json()) as { name?: string | null };
      const name = body.name ?? `${role.name} copy`;
      const copy = withScopes({
        ...role,
        id: `rol_copy_${role.slug.replace(/-/g, "_")}`,
        slug: `${role.slug}-copy`,
        name,
        kind: "custom",
        people: 0,
        groups: 0,
        service_accounts: 0,
        version: 1,
      });
      roles = [...roles, copy];
      return HttpResponse.json(copy, { status: 201 });
    }),
    http.delete(`${API}/access/roles/:role`, ({ params }) => {
      const role = find(String(params.role));
      if (!role) return problem(404, "not_found", "There is no such access role.");
      record?.deletes.push(role.id);
      if (role.kind === "built_in")
        return problem(
          422,
          "validation_failed",
          `${role.name} is built in; you can change it, but not delete it.`,
        );
      const bound = BINDINGS.filter((item) => item.role_id === role.id);
      if (bound.length)
        return problem(
          409,
          "conflict",
          `${role.name} is still bound ${String(bound.length)} times; remove those bindings first.`,
          {
            bindings: bound.map((item) => ({
              id: item.id,
              principal_kind: item.principal_kind,
              principal_id: item.principal_id,
              principal_name:
                item.principal_kind === "group"
                  ? (GROUP_NAMES[item.principal_id] ?? item.principal_id)
                  : (sampleMembers.find((member) => member.user_id === item.principal_id)?.display_name ??
                    item.principal_id),
              instance_id: item.instance_id,
            })),
          },
        );
      roles = roles.filter((item) => item.id !== role.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/access/roles/:role/versions`, ({ params }) => {
      const role = find(String(params.role));
      return role ? HttpResponse.json(versionsOf(role)) : problem(404, "not_found", "There is no such role.");
    }),
    http.get(`${API}/access/roles/:role/holders`, ({ params }) => {
      const role = find(String(params.role));
      if (!role) return problem(404, "not_found", "There is no such access role.");
      return HttpResponse.json({
        reach: reachOf(role),
        bindings: BINDINGS.filter((item) => item.role_id === role.id),
      });
    }),
  ];
}

export function emptyRolesRecord(): RolesRecord {
  return { previews: [], updates: [], resets: [], deletes: [], creates: [] };
}
