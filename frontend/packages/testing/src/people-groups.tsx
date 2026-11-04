// People & groups fixtures from the prototype's sample org: members with their groups, manual and SCIM-synced groups
// with role bindings, temporary access requests, invitations, the scope catalog and SCIM status; plus MSW handlers.
// Built on the base sample org (Daniel Okafor, Marcus Chen, prod and staging), which stays as it is.
import type {
  AccessRequestOut,
  BindingCreate,
  BindingOut,
  BulkOutcomeOut,
  ExplainIn,
  ExplanationOut,
  GroupCreate,
  GroupDetailOut,
  GroupMemberIn,
  GroupOut,
  GroupUpdate,
  InvitationOut,
  MemberOut,
  MembersBulk,
  RoleOut,
  RouteOut,
  ScimStatusOut,
  ScopeOut,
  TemporaryGrantIn,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { DANIEL, MARCUS, PROD, STAGING, sampleBindings, sampleMembers, sampleRoles } from "./sample-org";

const NOW = Date.now();
const MINUTE = 60_000;
const ago = (minutes: number) => new Date(NOW - minutes * MINUTE).toISOString();
const ahead = (minutes: number) => new Date(NOW + minutes * MINUTE).toISOString();
const HOUR = 60;
const DAY = 24 * HOUR;

/** People added to the base sample org (ids follow the base fixtures' shape). */
export const PEOPLE = {
  daniel: DANIEL,
  marcus: MARCUS,
  sam: "usr_01M6A0EEZEQ373S26F20142SAM",
  maya: "usr_01M6A0EEZEQ373S26F2014MAYA",
  priya: "usr_01M6A0EEZEQ373S26F201PRIYA",
  lena: "usr_01M6A0EEZEQ373S26F20142LEN",
  omar: "usr_01M6A0EEZEQ373S26F20142OMR",
  jonas: "usr_01M6A0EEZEQ373S26F20142JON",
  aiko: "usr_01M6A0EEZEQ373S26F20142AIK",
} as const;

export const PEOPLE_GROUPS = {
  platform: "grp_01M6A0EEZEQ373S26F2PLATFRM",
  support: "grp_01M6A0EEZEQ373S26F2SUPPORT",
  billing: "grp_01M6A0EEZEQ373S26F2BILLING",
  research: "grp_01M6A0EEZEQ373S26F2RESRCH",
  finance: "grp_01M6A0EEZEQ373S26F2FINANCE",
} as const;

const ROLE_COLORS: Record<string, string> = {
  "instance-admin": "#C5F25C",
  operator: "#F2B54B",
  builder: "#9DBBFF",
  viewer: "#A9AFB8",
};

/** The base roles with the colors the role editor gives them. */
export const peopleRoles: RoleOut[] = sampleRoles.map((role) => ({
  ...role,
  color: ROLE_COLORS[role.slug] ?? role.color,
}));

function roleId(slug: string): string {
  const found = sampleRoles.find((role) => role.slug === slug);
  if (!found) throw new Error(`No sample role ${slug}`);
  return found.id;
}

function group(
  id: string,
  name: string,
  description: string,
  synced: string | null,
  memberCount: number,
): GroupOut {
  return {
    id,
    name,
    description,
    source: synced ? "scim" : "manual",
    external_id: synced ? `00g${synced}` : null,
    external_name: synced,
    sync_label: synced ? `SCIM · ${synced}` : "Manual",
    synced: Boolean(synced),
    member_count: memberCount,
    created_at: ago(90 * DAY),
    updated_at: ago(3 * DAY),
  };
}

export const peopleGroups: GroupOut[] = [
  group(PEOPLE_GROUPS.platform, "Platform", "Runs the control plane", null, 2),
  group(PEOPLE_GROUPS.support, "Support AI", "Owns support-triage and ticket-router", "support-ai", 3),
  group(PEOPLE_GROUPS.billing, "Billing ops", "Approves refunds", "billing", 2),
  group(PEOPLE_GROUPS.research, "Research", "Builds research-team", null, 1),
  group(PEOPLE_GROUPS.finance, "Finance", "Reads usage and cost", "finance", 1),
];

const groupRef = (id: string) => {
  const found = peopleGroups.find((item) => item.id === id);
  if (!found) throw new Error(`No sample group ${id}`);
  return { id: found.id, name: found.name };
};

function person(
  id: string,
  name: string,
  email: string,
  orgRole: MemberOut["org_role"],
  groups: string[],
  lastActiveMinutes: number,
): MemberOut {
  return {
    user_id: id,
    email,
    display_name: name,
    avatar_seed: email,
    org_role: orgRole,
    joined_at: "2026-03-12T09:00:00Z",
    joined_via: "sso:okta",
    last_active_at: ago(lastActiveMinutes),
    groups: groups.map(groupRef),
  };
}

const base = (id: string): MemberOut => {
  const found = sampleMembers.find((member) => member.user_id === id);
  if (!found) throw new Error(`No sample member ${id}`);
  return found;
};

export const peopleMembers: MemberOut[] = [
  { ...base(DANIEL), last_active_at: ago(2), groups: [groupRef(PEOPLE_GROUPS.platform)] },
  person(PEOPLE.sam, "Sam Rivera", "sam@localhost.company", "administrator", [PEOPLE_GROUPS.platform], HOUR),
  person(
    PEOPLE.maya,
    "Maya Chen",
    "maya@localhost.company",
    "member",
    [PEOPLE_GROUPS.support, PEOPLE_GROUPS.billing],
    12,
  ),
  { ...base(MARCUS), groups: [] },
  person(PEOPLE.priya, "Priya Nair", "priya@localhost.company", "member", [PEOPLE_GROUPS.support], 3 * HOUR),
  person(PEOPLE.lena, "Lena Ito", "lena@localhost.company", "member", [PEOPLE_GROUPS.research], 5 * HOUR),
  person(PEOPLE.omar, "Omar Haddad", "omar@localhost.company", "member", [PEOPLE_GROUPS.billing], DAY),
  person(PEOPLE.jonas, "Jonas Weber", "jonas@localhost.company", "member", [PEOPLE_GROUPS.finance], 3 * DAY),
  person(PEOPLE.aiko, "Aiko Tan", "aiko@localhost.company", "member", [], 7 * DAY),
];

function binding(
  id: string,
  kind: BindingOut["principal_kind"],
  principal: string,
  instance: string | null,
  grant: { role: string } | { scopes: string[] },
  extra: Partial<BindingOut> = {},
): BindingOut {
  return {
    id,
    principal_kind: kind,
    principal_id: principal,
    instance_id: instance,
    role_id: "role" in grant ? roleId(grant.role) : null,
    scopes: "scopes" in grant ? grant.scopes : [],
    expires_at: null,
    reason: null,
    created_by: DANIEL,
    created_at: ago(30 * DAY),
    ...extra,
  };
}

/** The base bindings (Marcus's Operator on prod), group bindings and a few direct ones. */
export const peopleBindings: BindingOut[] = [
  ...sampleBindings,
  binding("bnd_grp_platform", "group", PEOPLE_GROUPS.platform, null, { role: "instance-admin" }),
  binding("bnd_grp_support_prod", "group", PEOPLE_GROUPS.support, PROD, { role: "operator" }),
  binding("bnd_grp_support_stg", "group", PEOPLE_GROUPS.support, STAGING, { role: "builder" }),
  binding("bnd_grp_billing_prod", "group", PEOPLE_GROUPS.billing, PROD, { role: "operator" }),
  binding("bnd_grp_billing_run", "group", PEOPLE_GROUPS.billing, PROD, {
    scopes: ["agents:billing-agent:run"],
  }),
  binding("bnd_grp_research", "group", PEOPLE_GROUPS.research, STAGING, { role: "builder" }),
  binding("bnd_grp_finance", "group", PEOPLE_GROUPS.finance, PROD, { role: "viewer" }),
  binding("bnd_usr_aiko", "user", PEOPLE.aiko, null, { role: "viewer" }),
  binding(
    "bnd_usr_lena",
    "user",
    PEOPLE.lena,
    PROD,
    { role: "viewer" },
    { expires_at: "2026-11-30T12:00:00Z", reason: "Incident review" },
  ),
];

function members(groupId: string): GroupDetailOut["members"] {
  const owners: Record<string, string> = {
    [PEOPLE_GROUPS.platform]: DANIEL,
    [PEOPLE_GROUPS.support]: PEOPLE.maya,
    [PEOPLE_GROUPS.billing]: PEOPLE.omar,
  };
  const found = peopleGroups.find((item) => item.id === groupId);
  return peopleMembers
    .filter((member) => member.groups?.some((ref) => ref.id === groupId))
    .map((member) => ({
      user_id: member.user_id,
      display_name: member.display_name,
      email: member.email,
      role: owners[groupId] === member.user_id ? "owner" : "member",
      source: found?.source ?? "manual",
    }));
}

export function peopleGroupDetail(id: string): GroupDetailOut | undefined {
  const found = peopleGroups.find((item) => item.id === id);
  return found ? { ...found, members: members(id) } : undefined;
}

/** "Approvals routed here": routing rules naming Support AI. */
export const peopleGroupRoutes: Record<string, RouteOut[]> = {
  [PEOPLE_GROUPS.support]: [
    {
      id: "rte_refunds",
      name: "Refunds",
      instance_id: PROD,
      tool_name: "refund_customer",
      component_kind: "agent",
      component_ids: ["support-triage", "billing-agent"],
      groups: [groupRef(PEOPLE_GROUPS.support)],
      members: [],
      roles: [],
      channels: ["in_app", "slack"],
      channel_ids: [],
      created_by: DANIEL,
      updated_at: ago(3 * DAY),
    },
  ],
};

function request(fields: Partial<AccessRequestOut> & Pick<AccessRequestOut, "id" | "requester_id">) {
  return {
    instance_id: STAGING,
    role_id: roleId("builder"),
    scopes: [],
    duration_hours: 8,
    reason: "",
    status: "pending",
    note: null,
    binding_id: null,
    decided_at: null,
    decided_by: null,
    expires_at: null,
    can_decide: true,
    created_at: ago(25),
    ...fields,
  } satisfies AccessRequestOut;
}

export const peopleRequests: AccessRequestOut[] = [
  request({
    id: "req_omar_builder",
    requester_id: PEOPLE.omar,
    reason: "Fix the refund prompt before Friday's release",
  }),
  request({
    id: "req_daniel_admin",
    requester_id: DANIEL,
    instance_id: PROD,
    role_id: null,
    scopes: ["agent_os:admin"],
    duration_hours: 2,
    reason: "Rotate the gateway key during the incident",
    can_decide: false,
    created_at: ago(8),
  }),
  request({
    id: "req_lena_viewer",
    requester_id: PEOPLE.lena,
    instance_id: PROD,
    role_id: roleId("viewer"),
    duration_hours: 72,
    reason: "Incident review",
    status: "approved",
    decided_by: DANIEL,
    decided_at: ago(2 * DAY),
    binding_id: "bnd_usr_lena",
    expires_at: ago(-DAY),
    can_decide: false,
    created_at: ago(2 * DAY + 30),
  }),
];

export const peopleInvitations: InvitationOut[] = [
  {
    id: "inv_01M6A0EEZEQ373S26F2014RAFA",
    email: "rafael@localhost.company",
    org_role: "member",
    bindings: [{ role_id: roleId("operator"), instance_id: PROD }],
    group_ids: [PEOPLE_GROUPS.billing],
    access_ends_at: null,
    invited_by: PEOPLE.sam,
    expires_at: ahead(6 * DAY),
    status: "pending",
    created_at: ago(DAY),
  },
  {
    id: "inv_01M6A0EEZEQ373S26F2014SING",
    email: "k.singh@contractor.io",
    org_role: "member",
    bindings: [{ role_id: roleId("viewer"), instance_id: STAGING }],
    group_ids: [],
    access_ends_at: "2026-11-30T12:00:00Z",
    invited_by: DANIEL,
    expires_at: ahead(2 * DAY),
    status: "pending",
    created_at: ago(5 * DAY),
  },
];

export const peopleScim: ScimStatusOut = {
  endpoint_url: "http://agnostic.test/scim/v2",
  healthy: true,
  last_error: null,
  last_error_at: null,
  last_request_at: ago(4),
  counts: { users: 21, groups: 3 },
  tokens: [
    {
      id: "sct_okta",
      label: "Okta SCIM",
      prefix: "scim_9f2",
      state: "active",
      created_at: ago(60 * DAY),
      created_by: DANIEL,
      expires_at: null,
      last_used_at: ago(4),
      rotated_from: null,
    },
  ],
};

function scopes(family: string, actions: string[], label: string, hidden = false): ScopeOut[] {
  const perComponent = ["agents", "teams", "workflows"].includes(family);
  return actions.map((action) => ({
    scope: `${family}:${action}`,
    family,
    action,
    source: "agentos",
    description: `${action} ${label}`,
    resource_kind: perComponent ? "per_component" : "global",
    privileged: action === "write" || action === "delete",
    hidden,
  }));
}

/** A slice of the scope catalog (one hidden family, which pickers leave out). */
export const peopleScopes: ScopeOut[] = [
  ...scopes("agents", ["read", "run", "write", "delete"], "agents"),
  ...scopes("workflows", ["read", "run"], "workflows"),
  ...scopes("components", ["read", "write"], "Studio components"),
  ...scopes("sessions", ["read", "delete"], "sessions"),
  ...scopes("knowledge", ["read", "write"], "knowledge"),
  ...scopes("approvals", ["read", "write"], "approvals"),
  ...scopes("wiki", ["read"], "the Company wiki", true),
];

const problem = (status: number, title: string, detail: string) =>
  HttpResponse.json({ type: "about:blank", title, status, detail, code: "invalid" }, { status });

/** MSW handlers for People & groups; stateful per call, so writes show up in the next read. */
export function peopleGroupsHandlers() {
  let groups = [...peopleGroups];
  let bindings = [...peopleBindings];
  let requests = [...peopleRequests];
  const details = new Map<string, GroupDetailOut>();
  const detail = (id: string) => {
    const known = details.get(id) ?? peopleGroupDetail(id);
    const current = groups.find((item) => item.id === id);
    return known && current ? { ...known, ...current, member_count: known.members.length } : undefined;
  };
  const save = (next: GroupDetailOut) => {
    details.set(next.id, next);
    groups = groups.map((item) =>
      item.id === next.id ? { ...item, member_count: next.members.length } : item,
    );
    return HttpResponse.json(next);
  };
  return [
    http.get(`${API}/members`, () => HttpResponse.json(peopleMembers)),
    http.post(`${API}/members/bulk`, async ({ request: req }) => {
      const body = (await req.json()) as MembersBulk;
      const outcomes: BulkOutcomeOut[] = body.user_ids.map((id) =>
        id === DANIEL && body.operation !== "add_to_group"
          ? { user_id: id, ok: false, error: "You can't change your own membership in bulk." }
          : { user_id: id, ok: true, error: null },
      );
      return HttpResponse.json(outcomes);
    }),
    http.get(`${API}/access/roles`, () => HttpResponse.json(peopleRoles)),
    http.get(`${API}/access/scopes`, () => HttpResponse.json(peopleScopes)),
    http.get(`${API}/access/bindings`, ({ request: req }) => {
      const kind = new URL(req.url).searchParams.get("principal_kind");
      return HttpResponse.json(kind ? bindings.filter((item) => item.principal_kind === kind) : bindings);
    }),
    http.post(`${API}/access/bindings`, async ({ request: req }) => {
      const body = (await req.json()) as BindingCreate;
      const created: BindingOut = {
        id: `bnd_new_${String(bindings.length)}`,
        principal_kind: body.principal_kind ?? "user",
        principal_id: body.principal_id ?? body.user_id ?? "",
        instance_id: body.instance ?? null,
        role_id: body.role_id ?? null,
        scopes: body.scopes ?? [],
        expires_at: body.expires_at ?? null,
        reason: body.reason ?? null,
        created_by: DANIEL,
        created_at: new Date().toISOString(),
      };
      bindings = [...bindings, created];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.delete(`${API}/access/bindings/:binding`, ({ params }) => {
      bindings = bindings.filter((item) => item.id !== params.binding);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(`${API}/access/temporary`, async ({ request: req }) => {
      const body = (await req.json()) as TemporaryGrantIn;
      const created: BindingOut = {
        id: `bnd_tmp_${String(bindings.length)}`,
        principal_kind: body.principal_kind ?? "user",
        principal_id: body.principal_id,
        instance_id: body.instance ?? null,
        role_id: body.role_id ?? null,
        scopes: body.scopes ?? [],
        expires_at: ahead(body.duration_hours * HOUR),
        reason: body.reason,
        created_by: DANIEL,
        created_at: new Date().toISOString(),
      };
      bindings = [...bindings, created];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.post(`${API}/access/explain`, async ({ request: req }) => {
      const body = (await req.json()) as ExplainIn;
      const scope = body.component
        ? `${body.resource ?? ""}:${body.component}:${body.verb ?? ""}`
        : `${body.resource ?? ""}:${body.verb ?? ""}`;
      const allowed = scope === "agents:billing-agent:run";
      const answer: ExplanationOut = allowed
        ? {
            allowed: true,
            scope,
            instance_id: PROD,
            granted_by: [
              {
                binding_id: "bnd_grp_billing_run",
                expires_at: null,
                instance_id: PROD,
                role_id: null,
                role_name: "Billing ops",
                scope,
                source: "binding",
                via_group_id: PEOPLE_GROUPS.billing,
                via_group_name: "Billing ops",
              },
            ],
            missing_scopes: [],
            alternatives: [],
            explanation:
              "Granted by Billing ops via Billing ops → `agents:billing-agent:run` on prod-agentos.",
            via_group: "Billing ops",
          }
        : {
            allowed: false,
            scope,
            instance_id: PROD,
            granted_by: [],
            missing_scopes: [scope],
            alternatives: [{ kind: "role", label: "Builder", role_name: "Builder" }],
            explanation: `This needs \`${scope}\` on prod-agentos. Maya Chen has Operator there, which doesn't include it. Builder has it on staging-agentos.`,
            can_request: true,
          };
      return HttpResponse.json(answer);
    }),
    http.get(`${API}/access/requests`, ({ request: req }) => {
      const status = new URL(req.url).searchParams.get("status");
      return HttpResponse.json(status ? requests.filter((item) => item.status === status) : requests);
    }),
    ...(["approve", "deny", "cancel"] as const).map((verb) =>
      http.post(`${API}/access/requests/:request/${verb}`, async ({ request: req, params }) => {
        const current = requests.find((item) => item.id === params.request);
        if (!current) return problem(404, "Not found", "There is no such request.");
        const body = verb === "cancel" ? {} : ((await req.json()) as { note?: string | null });
        const status = verb === "approve" ? "approved" : verb === "deny" ? "denied" : "cancelled";
        const updated: AccessRequestOut = {
          ...current,
          status,
          note: "note" in body ? (body.note ?? null) : null,
          decided_by: DANIEL,
          decided_at: new Date().toISOString(),
          can_decide: false,
        };
        requests = requests.map((item) => (item.id === updated.id ? updated : item));
        return HttpResponse.json(updated);
      }),
    ),
    http.get(`${API}/directory/scim`, () => HttpResponse.json(peopleScim)),
    http.get(`${API}/directory/groups`, () => HttpResponse.json(groups)),
    http.post(`${API}/directory/groups`, async ({ request: req }) => {
      const body = (await req.json()) as GroupCreate;
      if (groups.some((item) => item.name === body.name.trim()))
        return problem(409, "Conflict", `There already is a group called ${body.name}.`);
      const people = [...new Set([...(body.owner_ids ?? []), ...(body.member_ids ?? [])])];
      const created: GroupOut = {
        ...group(`grp_new_${String(groups.length)}`, body.name.trim(), body.description ?? "", null, 0),
        member_count: people.length,
      };
      groups = [...groups, created];
      const next: GroupDetailOut = {
        ...created,
        members: people.map((id) => {
          const member = peopleMembers.find((item) => item.user_id === id);
          return {
            user_id: id,
            display_name: member?.display_name ?? id,
            email: member?.email ?? "",
            role: body.owner_ids?.includes(id) ? "owner" : "member",
            source: "manual",
          };
        }),
      };
      details.set(created.id, next);
      return HttpResponse.json(next, { status: 201 });
    }),
    http.get(`${API}/directory/groups/:group`, ({ params }) => {
      const found = detail(String(params.group));
      return found ? HttpResponse.json(found) : problem(404, "Not found", "There is no such group.");
    }),
    http.patch(`${API}/directory/groups/:group`, async ({ request: req, params }) => {
      const body = (await req.json()) as GroupUpdate;
      groups = groups.map((item) =>
        item.id === params.group
          ? { ...item, name: body.name ?? item.name, description: body.description ?? item.description }
          : item,
      );
      const found = detail(String(params.group));
      return found ? save(found) : problem(404, "Not found", "There is no such group.");
    }),
    http.delete(`${API}/directory/groups/:group`, ({ params }) => {
      groups = groups.filter((item) => item.id !== params.group);
      bindings = bindings.filter((item) => item.principal_id !== params.group);
      return new HttpResponse(null, { status: 204 });
    }),
    http.put(`${API}/directory/groups/:group/members/:user`, async ({ request: req, params }) => {
      const body = (await req.json()) as GroupMemberIn;
      const found = detail(String(params.group));
      if (!found) return problem(404, "Not found", "There is no such group.");
      const exists = found.members.some((item) => item.user_id === params.user);
      if (found.synced && !exists)
        return problem(422, "Invalid", `${found.name} is synced from the IdP; add people there.`);
      const member = peopleMembers.find((item) => item.user_id === params.user);
      const row = {
        user_id: String(params.user),
        display_name: member?.display_name ?? String(params.user),
        email: member?.email ?? "",
        role: body.role ?? "member",
        source: found.source,
      };
      return save({
        ...found,
        members: exists
          ? found.members.map((item) => (item.user_id === row.user_id ? row : item))
          : [...found.members, row],
      });
    }),
    http.delete(`${API}/directory/groups/:group/members/:user`, ({ params }) => {
      const found = detail(String(params.group));
      if (!found) return problem(404, "Not found", "There is no such group.");
      return save({ ...found, members: found.members.filter((item) => item.user_id !== params.user) });
    }),
    http.get(`${API}/approvals/routes/by-group/:group`, ({ params }) =>
      HttpResponse.json(peopleGroupRoutes[String(params.group)] ?? []),
    ),
    http.get(`${API}/invitations`, () => HttpResponse.json(peopleInvitations)),
  ];
}
