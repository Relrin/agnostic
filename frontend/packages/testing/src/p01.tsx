// P01 fixtures (the prototype's sample org) and MSW handlers for identity, org, instances, access and audit.
import type {
  AuditEventOut,
  BindingOut,
  CapabilityOut,
  InstanceOut,
  InvitationOut,
  MemberOut,
  MeOut,
  MyAccessOut,
  OrgOut,
  RoleOut,
} from "@agnostic/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { render, type RenderResult } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { API, configureTestApi } from "./base";

/** Render a page inside a minimal router (the page sees `path` params and `url` search params). */
export function renderPage(
  Page: () => ReactNode,
  { path = "/", url = path }: { path?: string; url?: string } = {},
): RenderResult & { queryClient: QueryClient } {
  configureTestApi();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const rootRoute = createRootRoute({ component: Outlet });
  const pageRoute = createRoute({ getParentRoute: () => rootRoute, path, component: Page });
  const catchAll = createRoute({
    getParentRoute: () => rootRoute,
    path: "$",
    component: () => <p>Navigated away</p>,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([pageRoute, catchAll]),
    history: createMemoryHistory({ initialEntries: [url] }),
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

const T = "2026-11-01T09:00:00Z";
export const DANIEL = "usr_01M6A0EEZEQ373S26F20142DAN";
export const MARCUS = "usr_01M6A0EEZEQ373S26F20142MAY";
export const PROD = "ins_01M6A0EEZEQ373S26F2014PRD";
export const STAGING = "ins_01M6A0EEZEQ373S26F2014STG";

export const sampleMe: MeOut = {
  id: DANIEL,
  email: "daniel@localhost.company",
  display_name: "Daniel Okafor",
  avatar_seed: "abc",
  locale: null,
  timezone: null,
  org_role: "owner",
  preferences: {},
  has_password: true,
  sso_providers: [],
  session_method: "password",
  created_at: T,
  last_active_at: T,
};

export const sampleOrg: OrgOut = {
  name: "Localhost Company",
  slug: "localhost-company",
  logo_url: null,
  plan_label: null,
  seat_limit: 24,
  member_count: 2,
  pending_invitations: 1,
  viewer_role: "owner",
  settings: { require_explicit_bindings: false, audit_log_all_reads: false },
  updated_at: T,
};

function instance(
  id: string,
  slug: string,
  env: InstanceOut["env_tag"],
  status: InstanceOut["status"],
): InstanceOut {
  return {
    id,
    slug,
    display_name: slug,
    env_tag: env,
    endpoint_url: `http://${slug}.internal:7777`,
    os_id: `${slug}-os`,
    agno_version: "3.1.12",
    os_version: "3.1.12",
    auth_mode: "jwt",
    user_isolation: env === "production",
    elevation_enabled: true,
    status,
    last_seen_at: T,
    latency_ms: 38,
    sub_claim_mode: "user_id",
    tls_verify: true,
    has_ca_bundle: false,
    has_security_key: false,
    version_drift: null,
    created_at: T,
    updated_at: T,
    version: 3,
  };
}

export const sampleInstances: InstanceOut[] = [
  instance(PROD, "prod-agentos", "production", "connected"),
  instance(STAGING, "staging-agentos", "staging", "connected"),
];

export const sampleCapabilities: CapabilityOut[] = [
  {
    name: "jwt_rbac",
    label: "Per-user permissions (JWT authorization enforced)",
    status: "available",
    detail: "",
  },
  { name: "approvals", label: "Approvals (human in the loop)", status: "disabled", detail: "not enabled" },
];

function role(slug: string, name: string, scopes: string[]): RoleOut {
  return {
    id: `rol_${slug.replace("-", "_")}`,
    slug,
    name,
    description: "",
    color: "#C5F25C",
    kind: "built_in",
    permissions: {},
    run_scope: {},
    bindable_instance_ids: null,
    scopes,
    people: 1,
    version: 1,
  };
}

export const sampleRoles: RoleOut[] = [
  role("instance-admin", "Instance admin", ["agent_os:admin"]),
  role("operator", "Operator", ["agents:read", "agents:run", "sessions:read", "approvals:write"]),
  role("builder", "Builder", ["components:write"]),
  role("viewer", "Viewer", ["sessions:read"]),
];

export const sampleMembers: MemberOut[] = [
  {
    user_id: DANIEL,
    email: "daniel@localhost.company",
    display_name: "Daniel Okafor",
    avatar_seed: "a",
    org_role: "owner",
    joined_at: T,
    joined_via: "bootstrap",
    last_active_at: T,
  },
  {
    user_id: MARCUS,
    email: "marcus@localhost.company",
    display_name: "Marcus Chen",
    avatar_seed: "b",
    org_role: "member",
    joined_at: T,
    joined_via: "sso:okta",
    last_active_at: null,
  },
];

export const sampleBindings: BindingOut[] = [
  {
    id: "bnd_01M6A0EEZEQ373S26F20142B01",
    principal_kind: "user",
    principal_id: MARCUS,
    instance_id: PROD,
    role_id: "rol_operator",
    scopes: [],
    expires_at: null,
    reason: null,
    created_by: DANIEL,
    created_at: T,
  },
];

export const sampleInvitations: InvitationOut[] = [
  {
    id: "inv_01M6A0EEZEQ373S26F20142I01",
    email: "jonas@localhost.company",
    org_role: "member",
    bindings: [{ role_id: "rol_viewer", instance_id: PROD }],
    access_ends_at: null,
    invited_by: DANIEL,
    expires_at: "2026-11-08T09:00:00Z",
    status: "pending",
    created_at: T,
  },
];

export const ownerAccess: MyAccessOut = {
  instance_id: null,
  org_role: "owner",
  implicit_full_access: true,
  roles: [],
  token_scopes: [],
  runtime_scopes: [],
  control_plane_scopes: [
    "org:read",
    "org:write",
    "org:members:read",
    "org:members:write",
    "org:roles:read",
    "org:roles:write",
    "os:read",
    "os:write",
    "os:delete",
    "os:keys:rotate",
    "audit:read",
    "evals:gates:write",
  ],
  grants: [],
};

export const sampleEvents: AuditEventOut[] = [
  {
    id: "evt_01M6A0EEZEQ373S26F20142E02",
    occurred_at: "2026-11-01T16:58:40Z",
    request_id: "req_1",
    actor: { kind: "user", id: MARCUS, display: "Marcus Chen" },
    via: "gateway",
    ip: "10.0.0.4",
    client: "Firefox",
    action: "gateway.denied",
    resource_kind: "route",
    resource_id: "DELETE /sessions/{session_id}",
    resource_display: "DELETE /sessions/x",
    instance_id: PROD,
    decision: "denied",
    scope_checked: "sessions:delete",
    missing_scopes: ["sessions:delete"],
    response_status: 403,
    summary: "Marcus Chen was denied DELETE /sessions/x on prod-agentos: missing sessions:delete",
    diff: null,
    links: null,
    source: "control_plane",
  },
  {
    id: "evt_01M6A0EEZEQ373S26F20142E01",
    occurred_at: "2026-11-01T16:42:03Z",
    request_id: "req_2",
    actor: { kind: "user", id: DANIEL, display: "Daniel Okafor" },
    via: "web",
    ip: "10.0.0.2",
    client: "Chrome",
    action: "members.update",
    resource_kind: "member",
    resource_id: MARCUS,
    resource_display: "Marcus Chen",
    instance_id: null,
    decision: "n_a",
    scope_checked: null,
    missing_scopes: [],
    response_status: null,
    summary: "Daniel Okafor changed Marcus Chen's org role from administrator to member",
    diff: { org_role: { before: "administrator", after: "member" } },
    links: null,
    source: "control_plane",
  },
];

/** MSW handlers for the P01 API with the sample org; override any with `server.use(...)`. */
export function p01Handlers() {
  return [
    http.get(`${API}/me`, () => HttpResponse.json(sampleMe)),
    http.get(`${API}/me/access`, ({ request }) => {
      const instance = new URL(request.url).searchParams.get("instance");
      if (!instance) return HttpResponse.json(ownerAccess);
      // Owners have implicit Full access on every instance.
      return HttpResponse.json({
        ...ownerAccess,
        instance_id: instance,
        roles: ["Full access"],
        token_scopes: ["agent_os:admin"],
        runtime_scopes: ["agent_os:admin"],
      });
    }),
    http.get(`${API}/org`, () => HttpResponse.json(sampleOrg)),
    http.get(`${API}/instances`, () => HttpResponse.json(sampleInstances)),
    http.get(`${API}/instances/:instance`, ({ params }) => {
      const found = sampleInstances.find(
        (item) => item.slug === params.instance || item.id === params.instance,
      );
      return found
        ? HttpResponse.json(found)
        : HttpResponse.json(
            { code: "not_found", status: 404, title: "Not found", type: "x" },
            { status: 404 },
          );
    }),
    http.get(`${API}/instances/:instance/health`, ({ params }) => {
      const found = sampleInstances.find(
        (item) => item.slug === params.instance || item.id === params.instance,
      );
      return HttpResponse.json({
        instance_id: found?.id ?? PROD,
        status: found?.status ?? "connected",
        latency_ms: 38,
        last_seen_at: T,
        agno_version: "3.1.12",
        version_drift: null,
        capabilities: sampleCapabilities,
        probed_at: T,
      });
    }),
    http.get(`${API}/members`, () => HttpResponse.json(sampleMembers)),
    http.get(`${API}/access/roles`, () => HttpResponse.json(sampleRoles)),
    http.get(`${API}/access/bindings`, () => HttpResponse.json(sampleBindings)),
    http.get(`${API}/invitations`, () => HttpResponse.json(sampleInvitations)),
    http.get(`${API}/audit/events`, () => HttpResponse.json({ data: sampleEvents, next_cursor: null })),
  ];
}
