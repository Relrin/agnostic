// Organization settings fixtures (identity providers, sign-in policy, SCIM, Google sync, audit retention, SIEM
// sinks, your second factors) and stateful MSW handlers for them.
import type {
  ArchiveOut,
  AuditPolicyIn,
  AuditPolicyOut,
  AuthPolicyOut,
  AuthPolicyUpdate,
  GoogleSyncIn,
  GoogleSyncOut,
  GroupOut,
  MappingRuleCreate,
  MappingRuleOut,
  MfaOut,
  MyAccessOut,
  OrgOut,
  OrgUpdate,
  ProviderCreate,
  ProviderOut,
  ProviderUpdate,
  ScimStatusOut,
  ScimTokenOut,
  SinkIn,
  SinkOut,
  SinkPatch,
  StepUpOut,
  StreamStatusOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { DANIEL, MARCUS, ownerAccess, sampleOrg } from "./sample-org";

const T = "2026-11-01T09:00:00Z";
const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const ORIGIN = "http://agnostic.test";

/** An Owner who may change org settings, directory sync and the audit policy. */
export const orgAdminAccess: MyAccessOut = {
  ...ownerAccess,
  control_plane_scopes: [
    ...ownerAccess.control_plane_scopes,
    "settings:read",
    "settings:write",
    "org:members:write",
    "audit:export",
  ],
};

export const orgAuthProviders: ProviderOut[] = [
  {
    id: "github",
    kind: "oidc",
    preset: "github",
    display_name: "GitHub",
    enabled: true,
    managed_by: "config",
    allowed_email_domains: ["localhost.company"],
    jit_provisioning: false,
    trust_unverified_email: false,
    created_by: null,
    created_at: null,
    updated_at: null,
    oidc: {
      issuer: null,
      base_url: null,
      client_id: "Iv1.8a61f9b3a7aba766",
      has_client_secret: true,
      scopes: ["read:user", "user:email"],
      callback_url: `${ORIGIN}/api/v1/auth/sso/github/callback`,
    },
    saml: null,
  },
  {
    id: "okta-saml",
    kind: "saml",
    preset: "saml",
    display_name: "Okta",
    enabled: true,
    managed_by: "database",
    allowed_email_domains: ["localhost.company"],
    jit_provisioning: true,
    trust_unverified_email: false,
    created_by: DANIEL,
    created_at: T,
    updated_at: T,
    oidc: null,
    saml: {
      idp_entity_id: "http://www.okta.com/exk1fcia6d6EEbtcK4x7",
      sso_url: "https://localhost-company.okta.com/app/agnostic/exk1fcia6d6EEbtcK4x7/sso/saml",
      metadata_url: "https://localhost-company.okta.com/app/exk1fcia6d6EEbtcK4x7/sso/saml/metadata",
      name_id_format: "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
      attribute_mapping: { email: "email", name: "displayName", groups: "groups" },
      certificates: [
        {
          subject: "CN=localhost-company, OU=SSOProvider, O=Okta",
          not_after: "2036-10-30T00:00:00Z",
          fingerprint_sha256:
            "4F:A1:0C:9E:77:2B:D3:51:6A:08:E2:CC:91:3D:5F:B0:7E:44:19:A6:D2:8C:63:FE:01:B5:3A:97:E8:20:4C:DD",
        },
      ],
      sp_entity_id: `${ORIGIN}/api/v1/auth/sso/okta-saml/metadata`,
      acs_url: `${ORIGIN}/api/v1/auth/sso/okta-saml/acs`,
    },
  },
];

export const orgAuthPolicy: AuthPolicyOut = {
  enforce_sso: false,
  break_glass_user_id: null,
  break_glass_user: null,
  session_idle_minutes: null,
  session_absolute_hours: null,
  default_session_idle_minutes: 720,
  default_session_absolute_hours: 168,
  mfa_policy: "optional",
  updated_by: null,
  updated_at: null,
};

export const orgStepUp: StepUpOut = {
  authenticated_at: T,
  recent: false,
  expires_at: null,
  methods: ["password", "totp"],
  sso_providers: [],
};

const OKTA_SCIM_TOKEN: ScimTokenOut = {
  id: "sct_01M6A0EEZEQ373S26F20142T01",
  label: "Okta SCIM",
  prefix: "agn_scim_7Hq2",
  state: "active",
  created_by: DANIEL,
  created_at: T,
  last_used_at: minutesAgo(4),
  expires_at: null,
  rotated_from: null,
};

export const orgScimStatus: ScimStatusOut = {
  endpoint_url: `${ORIGIN}/scim/v2`,
  healthy: true,
  last_request_at: minutesAgo(4),
  last_error: null,
  last_error_at: null,
  counts: { users: 22, groups: 6 },
  tokens: [OKTA_SCIM_TOKEN],
};

export const orgDirectoryGroups: GroupOut[] = [
  {
    id: "grp_01M6A0EEZEQ373S26F20142G01",
    name: "Support AI",
    description: "",
    external_id: null,
    external_name: null,
    member_count: 4,
    source: "manual",
    sync_label: "Manual",
    synced: false,
    created_at: T,
    updated_at: T,
  },
  {
    id: "grp_01M6A0EEZEQ373S26F20142G02",
    name: "Platform",
    description: "",
    external_id: "00g1fcia6d6",
    external_name: "eng-platform",
    member_count: 7,
    source: "scim",
    sync_label: "Okta SCIM",
    synced: true,
    created_at: T,
    updated_at: T,
  },
];

export const orgMappingRules: MappingRuleOut[] = [
  {
    id: "dmr_01M6A0EEZEQ373S26F20142M01",
    source: "scim",
    idp_group: "eng-platform",
    group_id: "grp_01M6A0EEZEQ373S26F20142G02",
    group_name: "Platform",
    provider_id: null,
    created_by: DANIEL,
    created_at: T,
  },
];

export const orgGoogleSync: GoogleSyncOut = {
  configured: false,
  client_email: null,
  admin_subject: null,
  customer_id: null,
  group_filter: [],
  enabled: false,
  last_run_at: null,
  last_error: null,
  counts: {},
};

export const orgRetentionPolicy: AuditPolicyOut = {
  hot_retention_days: 400,
  archive_enabled: true,
  endpoint: "https://minio.internal:9000",
  bucket: "agnostic-audit",
  prefix: "audit/",
  region: "us-east-1",
  access_key_id: "AKIAAGNOSTIC",
  has_secret: true,
  object_lock_mode: "governance",
  archive_retention_days: null,
  hash_chain: true,
  updated_by: DANIEL,
  updated_at: T,
  last_archive_at: "2026-10-01T03:00:00Z",
  last_archive_error: null,
};

export const orgArchives: ArchiveOut[] = [
  {
    month: "2025-08",
    object_key: "audit/2025/08/events.jsonl.zst",
    manifest_key: "audit/2025/08/manifest.json",
    bytes: 18_874_368,
    event_count: 412_880,
    sha256: "9b1e5c0f4a7d2e8b6c3f1a0d9e8b7c6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c",
    chain_head: "c41f…",
    archived_at: "2026-10-01T03:00:00Z",
    purge_after: null,
    restored: false,
    restored_at: null,
    restore_expires_at: null,
  },
];

export const orgSinks: SinkOut[] = [
  {
    id: "snk_01M6A0EEZEQ373S26F20142S01",
    name: "Splunk HEC",
    kind: "https_webhook",
    format: "json",
    config: {
      url: "https://splunk.localhost.company:8088/services/collector/raw",
      header_names: ["Authorization"],
    },
    has_secret: true,
    enabled: true,
    status: "ok",
    failure_count: 0,
    last_event_at: minutesAgo(1),
    last_error: null,
    created_by: DANIEL,
    created_at: T,
  },
];

export const orgStreamStatus: StreamStatusOut = {
  streaming: true,
  last_event_at: minutesAgo(1),
  sinks: [],
};

/** Your second factors: an authenticator app, recovery codes left. */
export const sampleMyMfa: MfaOut = {
  policy: "optional",
  required: false,
  factors: [
    {
      id: "mfa_01M6A0EEZEQ373S26F20142F01",
      kind: "totp",
      label: "1Password",
      created_at: T,
      last_used_at: minutesAgo(60),
    },
  ],
  recovery_codes_left: 8,
};

export const sampleRecoveryCodes = [
  "7hq2-k9mx",
  "p4ld-2wze",
  "c8rn-y6tb",
  "m3vf-q5ja",
  "x1gs-e7uk",
  "b9hw-n4pd",
  "t6zc-r2lm",
  "f5ky-a8vq",
];

function providerFrom(body: ProviderCreate): ProviderOut {
  return {
    id: body.id,
    kind: body.kind,
    preset: body.preset ?? body.kind,
    display_name: body.display_name ?? body.id,
    enabled: body.enabled ?? true,
    managed_by: "database",
    allowed_email_domains: body.allowed_email_domains ?? [],
    jit_provisioning: body.jit_provisioning ?? false,
    trust_unverified_email: body.trust_unverified_email ?? false,
    created_by: DANIEL,
    created_at: T,
    updated_at: T,
    oidc:
      body.kind === "oidc"
        ? {
            issuer: body.issuer ?? null,
            base_url: body.base_url ?? null,
            client_id: body.client_id ?? "",
            has_client_secret: Boolean(body.client_secret),
            scopes: body.scopes ?? ["openid", "email", "profile"],
            callback_url: `${ORIGIN}/api/v1/auth/sso/${body.id}/callback`,
          }
        : null,
    saml:
      body.kind === "saml"
        ? {
            idp_entity_id: body.idp_entity_id ?? "http://idp.example.com",
            sso_url: body.sso_url ?? "https://idp.example.com/sso",
            metadata_url: body.metadata_url ?? null,
            name_id_format: body.name_id_format ?? "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            attribute_mapping: {
              email: body.attribute_mapping?.email ?? null,
              name: body.attribute_mapping?.name ?? null,
              groups: body.attribute_mapping?.groups ?? null,
            },
            certificates: [],
            sp_entity_id: `${ORIGIN}/api/v1/auth/sso/${body.id}/metadata`,
            acs_url: `${ORIGIN}/api/v1/auth/sso/${body.id}/acs`,
          }
        : null,
  };
}

/** The org settings APIs with the fixtures above (stateful); put them before `sampleOrgHandlers()`. */
export function orgSettingsHandlers() {
  let providers = [...orgAuthProviders];
  let policy = { ...orgAuthPolicy };
  let scim = structuredClone(orgScimStatus);
  let rules = [...orgMappingRules];
  let deprovision: "disable" | "remove" = "disable";
  let google = { ...orgGoogleSync };
  let retention = { ...orgRetentionPolicy };
  let archives = [...orgArchives];
  let sinks = [...orgSinks];
  let org: OrgOut = { ...sampleOrg, settings: { ...sampleOrg.settings, temporary_access_max_hours: 168 } };
  let tokenCount = 1;
  return [
    http.get(`${API}/me/access`, () => HttpResponse.json(orgAdminAccess)),
    http.get(`${API}/org`, () => HttpResponse.json(org)),
    http.patch(`${API}/org`, async ({ request }) => {
      const body = (await request.json()) as OrgUpdate;
      org = { ...org, settings: { ...org.settings, ...(body.settings as object) } };
      return HttpResponse.json(org);
    }),
    http.get(`${API}/auth/step-up`, () => HttpResponse.json(orgStepUp)),
    http.post(`${API}/auth/step-up`, () => HttpResponse.json({ ...orgStepUp, recent: true })),
    http.get(`${API}/auth/admin/providers`, () => HttpResponse.json(providers)),
    http.post(`${API}/auth/admin/providers`, async ({ request }) => {
      const created = providerFrom((await request.json()) as ProviderCreate);
      providers = [...providers, created];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.patch(`${API}/auth/admin/providers/:id`, async ({ request, params }) => {
      const body = (await request.json()) as ProviderUpdate;
      const current = providers.find((item) => item.id === params.id);
      if (!current)
        return HttpResponse.json({ status: 404, code: "not_found", title: "Not found" }, { status: 404 });
      const updated: ProviderOut = {
        ...current,
        display_name: body.display_name ?? current.display_name,
        enabled: body.enabled ?? current.enabled,
      };
      providers = providers.map((item) => (item.id === updated.id ? updated : item));
      return HttpResponse.json(updated);
    }),
    http.delete(`${API}/auth/admin/providers/:id`, ({ params }) => {
      providers = providers.filter((item) => item.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/auth/admin/policy`, () => HttpResponse.json(policy)),
    http.put(`${API}/auth/admin/policy`, async ({ request }) => {
      const body = (await request.json()) as AuthPolicyUpdate;
      policy = { ...policy, ...body, updated_by: DANIEL, updated_at: new Date().toISOString() };
      return HttpResponse.json(policy);
    }),
    http.get(`${API}/directory/scim`, () => HttpResponse.json(scim)),
    http.post(`${API}/directory/scim/tokens`, async ({ request }) => {
      const body = (await request.json()) as { label: string };
      tokenCount += 1;
      const token = {
        ...OKTA_SCIM_TOKEN,
        id: `sct_${String(tokenCount)}`,
        label: body.label,
        prefix: `agn_scim_${String(tokenCount)}xx`,
        last_used_at: null,
      };
      scim = { ...scim, tokens: [...scim.tokens, token] };
      return HttpResponse.json(
        { token, secret: `agn_scim_${String(tokenCount)}xx_s3cr3tVALUE` },
        { status: 201 },
      );
    }),
    http.post(`${API}/directory/scim/tokens/:id/rotate`, ({ params }) => {
      tokenCount += 1;
      const old = scim.tokens.find((item) => item.id === params.id);
      if (!old)
        return HttpResponse.json({ status: 404, code: "not_found", title: "Not found" }, { status: 404 });
      const token = { ...old, id: `sct_${String(tokenCount)}`, rotated_from: old.id, last_used_at: null };
      scim = {
        ...scim,
        tokens: [
          ...scim.tokens.map((item) =>
            item.id === old.id
              ? {
                  ...item,
                  state: "rotating" as const,
                  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
                }
              : item,
          ),
          token,
        ],
      };
      return HttpResponse.json({ token, secret: `agn_scim_${String(tokenCount)}_rotated` }, { status: 201 });
    }),
    http.delete(`${API}/directory/scim/tokens/:id`, ({ params }) => {
      scim = {
        ...scim,
        tokens: scim.tokens.map((item) =>
          item.id === params.id ? { ...item, state: "revoked" as const } : item,
        ),
      };
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/directory/groups`, () => HttpResponse.json(orgDirectoryGroups)),
    http.get(`${API}/directory/mapping-rules`, () => HttpResponse.json(rules)),
    http.post(`${API}/directory/mapping-rules`, async ({ request }) => {
      const body = (await request.json()) as MappingRuleCreate;
      const rule: MappingRuleOut = {
        id: `dmr_${String(rules.length + 1)}`,
        source: body.source,
        idp_group: body.idp_group,
        group_id: body.group_id,
        group_name: orgDirectoryGroups.find((group) => group.id === body.group_id)?.name ?? body.group_id,
        provider_id: body.provider_id ?? null,
        created_by: DANIEL,
        created_at: T,
      };
      rules = [...rules, rule];
      return HttpResponse.json(rule, { status: 201 });
    }),
    http.delete(`${API}/directory/mapping-rules/:id`, ({ params }) => {
      rules = rules.filter((rule) => rule.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/directory/settings`, () => HttpResponse.json({ deprovision })),
    http.put(`${API}/directory/settings`, async ({ request }) => {
      deprovision = ((await request.json()) as { deprovision: "disable" | "remove" }).deprovision;
      return HttpResponse.json({ deprovision });
    }),
    http.get(`${API}/directory/google`, () => HttpResponse.json(google)),
    http.put(`${API}/directory/google`, async ({ request }) => {
      const body = (await request.json()) as GoogleSyncIn;
      google = {
        ...google,
        configured: google.configured || Boolean(body.service_account_json),
        client_email: body.service_account_json
          ? "agnostic-sync@localhost-company.iam.gserviceaccount.com"
          : google.client_email,
        admin_subject: body.admin_subject ?? google.admin_subject,
        customer_id: body.customer_id ?? google.customer_id,
        group_filter: body.group_filter ?? google.group_filter,
        enabled: body.enabled ?? google.enabled,
      };
      return HttpResponse.json(google);
    }),
    http.post(`${API}/directory/google/test`, () =>
      HttpResponse.json({ ok: true, detail: "Read 6 groups and 24 users as admin@localhost.company." }),
    ),
    http.post(`${API}/directory/google/sync`, () => {
      google = { ...google, last_run_at: new Date().toISOString(), counts: { groups: 6, users: 24 } };
      return HttpResponse.json(google);
    }),
    http.get(`${API}/members`, () =>
      HttpResponse.json([
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
      ]),
    ),
    http.get(`${API}/audit/policy`, () => HttpResponse.json(retention)),
    http.put(`${API}/audit/policy`, async ({ request }) => {
      const body = (await request.json()) as AuditPolicyIn;
      const { secret_access_key: secret, ...rest } = body;
      retention = {
        ...retention,
        ...(Object.fromEntries(Object.entries(rest)) as Partial<AuditPolicyOut>),
        has_secret: secret === undefined ? retention.has_secret : secret !== "",
        updated_at: new Date().toISOString(),
      };
      return HttpResponse.json(retention);
    }),
    http.post(`${API}/audit/policy/test-write`, () =>
      HttpResponse.json({ ok: true, error: null, latency_ms: 42 }),
    ),
    http.get(`${API}/audit/archives`, () => HttpResponse.json(archives)),
    http.post(`${API}/audit/archives/:month/restore`, ({ params }) => {
      archives = archives.map((item) =>
        item.month === params.month
          ? {
              ...item,
              restored: true,
              restored_at: new Date().toISOString(),
              restore_expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
            }
          : item,
      );
      return HttpResponse.json({ month: params.month, status: "queued" }, { status: 202 });
    }),
    http.get(`${API}/audit/sinks`, () => HttpResponse.json(sinks)),
    http.post(`${API}/audit/sinks`, async ({ request }) => {
      const body = (await request.json()) as SinkIn;
      const { secret, headers, ...visible } = body.config as Record<string, unknown>;
      const sink: SinkOut = {
        id: `snk_${String(sinks.length + 1)}`,
        name: body.name,
        kind: body.kind,
        format: body.format ?? "json",
        config: headers ? { ...visible, header_names: Object.keys(headers) } : visible,
        has_secret: Boolean(secret),
        enabled: body.enabled ?? true,
        status: body.enabled === false ? "paused" : "ok",
        failure_count: 0,
        last_event_at: null,
        last_error: null,
        created_by: DANIEL,
        created_at: T,
      };
      sinks = [...sinks, sink];
      return HttpResponse.json(sink, { status: 201 });
    }),
    http.patch(`${API}/audit/sinks/:id`, async ({ request, params }) => {
      const body = (await request.json()) as SinkPatch;
      sinks = sinks.map((sink) =>
        sink.id === params.id
          ? {
              ...sink,
              name: body.name ?? sink.name,
              enabled: body.enabled ?? sink.enabled,
              status: body.enabled === false ? "paused" : body.enabled === true ? "ok" : sink.status,
            }
          : sink,
      );
      return HttpResponse.json(sinks.find((sink) => sink.id === params.id));
    }),
    http.delete(`${API}/audit/sinks/:id`, ({ params }) => {
      sinks = sinks.filter((sink) => sink.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post(`${API}/audit/sinks/:id/test`, () =>
      HttpResponse.json({ ok: true, status_code: 200, error: null, latency_ms: 87 }),
    ),
    http.get(`${API}/audit/stream-status`, () => HttpResponse.json(orgStreamStatus)),
  ];
}
