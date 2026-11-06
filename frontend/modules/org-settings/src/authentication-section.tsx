// Authentication: identity providers (OIDC and SAML 2.0), enforced SSO with a break-glass Owner, session
// lifetimes and the MFA policy. Every change here needs a recent sign-in (step-up).
import {
  apiUrl,
  authCreateProviderMutation,
  authDeleteProviderMutation,
  authGetPolicyOptions,
  authGetPolicyQueryKey,
  authListProvidersOptions,
  authListProvidersQueryKey,
  authSignInOptionsQueryKey,
  authUpdatePolicyMutation,
  authUpdateProviderMutation,
  describeError,
  membersListMembersOptions,
  type AuthPolicyOut,
  type AuthPolicyUpdate,
  type ProviderCreate,
  type ProviderOut,
  type ProviderUpdate,
} from "@agnostic/api";
import { formatWhen, useReauth, withQueryFn, withReauth } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  RadioCards,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusPill,
  Switch,
  Textarea,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState, type SubmitEvent } from "react";

import { CopyField, Facts, Section, optionalNumber, splitList, useWritable } from "./shared";

type Preset = NonNullable<ProviderCreate["preset"]>;
type OidcPreset = Exclude<Preset, "saml">;

const OIDC_PRESETS: { value: OidcPreset; label: string }[] = [
  { value: "okta", label: "Okta" },
  { value: "google", label: "Google Workspace" },
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "oidc", label: "Generic OIDC (Entra ID, Keycloak, Authentik, Dex…)" },
];

const PRESET_LABELS: Record<Preset, string> = {
  okta: "Okta",
  google: "Google",
  github: "GitHub",
  gitlab: "GitLab",
  oidc: "OIDC",
  saml: "SAML 2.0",
};

const MFA_OPTIONS = [
  {
    value: "off",
    label: "Off",
    description: "Nobody can add a new second factor. Existing ones are still asked.",
  },
  {
    value: "optional",
    label: "Optional",
    description: "Anyone can add an authenticator app or security key; once added it's always asked.",
  },
  {
    value: "required_local",
    label: "Required for passwords",
    description: "Every password sign-in needs a second factor; people without one enroll at sign-in.",
  },
  {
    value: "required_admins",
    label: "Required for admins",
    description: "Like the above, for Owners and Administrators only.",
  },
] as const;

const NAME_ID_FORMATS = [
  "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
  "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
  "urn:oasis:names:tc:SAML:2.0:nameid-format:unspecified",
];

/** Everything the provider dialog edits, as strings (the body is built from it). */
type ProviderForm = {
  kind: "oidc" | "saml";
  preset: OidcPreset;
  id: string;
  displayName: string;
  enabled: boolean;
  domains: string;
  jit: boolean;
  trustUnverified: boolean;
  issuer: string;
  baseUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
  samlSource: "url" | "xml" | "manual";
  metadataUrl: string;
  metadataXml: string;
  idpEntityId: string;
  ssoUrl: string;
  certificate: string;
  nameIdFormat: string;
  mapEmail: string;
  mapName: string;
  mapGroups: string;
  refreshMetadata: boolean;
};

export function formFrom(provider: ProviderOut | undefined, kind: "oidc" | "saml" = "oidc"): ProviderForm {
  const oidc = provider?.oidc;
  const saml = provider?.saml;
  return {
    kind: provider?.kind ?? kind,
    preset: provider && provider.preset !== "saml" ? provider.preset : "okta",
    id: provider?.id ?? "",
    displayName: provider?.display_name ?? "",
    enabled: provider?.enabled ?? true,
    domains: provider?.allowed_email_domains.join(", ") ?? "",
    jit: provider?.jit_provisioning ?? false,
    trustUnverified: provider?.trust_unverified_email ?? false,
    issuer: oidc?.issuer ?? "",
    baseUrl: oidc?.base_url && oidc.base_url !== "https://github.com" ? oidc.base_url : "",
    clientId: oidc?.client_id ?? "",
    clientSecret: "",
    scopes: oidc?.scopes.join(" ") ?? "",
    samlSource: saml && !saml.metadata_url ? "manual" : "url",
    metadataUrl: saml?.metadata_url ?? "",
    metadataXml: "",
    idpEntityId: saml?.idp_entity_id ?? "",
    ssoUrl: saml?.sso_url ?? "",
    certificate: "",
    nameIdFormat: saml?.name_id_format ?? "",
    mapEmail: saml?.attribute_mapping.email ?? "",
    mapName: saml?.attribute_mapping.name ?? "",
    mapGroups: saml?.attribute_mapping.groups ?? "",
    refreshMetadata: false,
  };
}

const orNull = (value: string) => (value.trim() === "" ? null : value.trim());

/** Switching presets drops what the old preset filled in (a GitHub URL is no GitLab URL). */
export function withPreset(form: ProviderForm, preset: OidcPreset): ProviderForm {
  if (preset === form.preset) return form;
  return { ...form, preset, issuer: "", baseUrl: "", scopes: "" };
}

/** The issuer GitLab sign-in will use: the instance URL, or gitlab.com. */
export function gitlabIssuer(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, "") || "https://gitlab.com";
}

/** The flat create/update body: only what the kind (and SAML source) uses; an empty secret keeps the saved one. */
export function providerBody(form: ProviderForm): Omit<ProviderCreate, "id" | "kind"> & ProviderUpdate {
  const common = {
    display_name: orNull(form.displayName),
    enabled: form.enabled,
    allowed_email_domains: splitList(form.domains),
    jit_provisioning: form.jit,
    trust_unverified_email: form.trustUnverified,
  };
  if (form.kind === "oidc") {
    return {
      ...common,
      preset: form.preset,
      client_id: form.clientId.trim(),
      ...(form.clientSecret ? { client_secret: form.clientSecret } : {}),
      ...(form.preset === "gitlab" || form.preset === "github" ? { base_url: orNull(form.baseUrl) } : {}),
      ...(["oidc", "okta", "google"].includes(form.preset) ? { issuer: orNull(form.issuer) } : {}),
      ...(form.scopes.trim() ? { scopes: form.scopes.trim().split(/[\s,]+/) } : {}),
    };
  }
  const mapping = {
    email: orNull(form.mapEmail),
    name: orNull(form.mapName),
    groups: orNull(form.mapGroups),
  };
  return {
    ...common,
    preset: "saml",
    ...(form.samlSource === "url" ? { metadata_url: form.metadataUrl.trim() } : {}),
    ...(form.samlSource === "url" && form.refreshMetadata ? { refresh_metadata: true } : {}),
    ...(form.samlSource === "xml" ? { metadata_xml: form.metadataXml } : {}),
    ...(form.samlSource === "manual"
      ? {
          idp_entity_id: form.idpEntityId.trim(),
          sso_url: form.ssoUrl.trim(),
          ...(form.certificate.trim() ? { certificates: [form.certificate.trim()] } : {}),
        }
      : {}),
    ...(form.nameIdFormat.trim() ? { name_id_format: form.nameIdFormat.trim() } : {}),
    attribute_mapping: mapping,
  };
}

function TextField({
  label,
  value,
  onChange,
  hint,
  mono = true,
  type = "text",
  required = false,
  disabled = false,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string | undefined;
  mono?: boolean;
  type?: string;
  required?: boolean;
  disabled?: boolean;
  placeholder?: string | undefined;
}) {
  return (
    <Field label={label} hint={hint}>
      {({ id, describedBy }) => (
        <Input
          id={id}
          mono={mono}
          type={type}
          required={required}
          disabled={disabled}
          placeholder={placeholder}
          value={value}
          aria-describedby={describedBy}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </Field>
  );
}

function SpDetails({ provider }: { provider: ProviderOut }) {
  if (!provider.saml) return null;
  return (
    <div className="flex flex-col gap-3 rounded-tile border border-border bg-inset p-3">
      <p className="text-[12.5px] text-fg-secondary">
        Copy these into your identity provider's SAML app (or give it the metadata file).
      </p>
      <Field label="SP entity ID (audience)">
        {() => <CopyField label="SP entity ID" value={provider.saml?.sp_entity_id ?? ""} />}
      </Field>
      <Field label="ACS URL (reply URL)">
        {() => <CopyField label="ACS URL" value={provider.saml?.acs_url ?? ""} />}
      </Field>
      <div>
        <Button asChild variant="outline" size="30">
          <a
            href={apiUrl(`/api/v1/auth/admin/providers/${encodeURIComponent(provider.id)}/saml-metadata`)}
            download={`${provider.id}-sp-metadata.xml`}
          >
            <Download aria-hidden />
            Download SP metadata
          </a>
        </Button>
      </div>
      {provider.saml.certificates.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-medium text-fg-secondary">IdP signing certificates</span>
          <ul className="flex flex-col gap-1 text-[12px]">
            {provider.saml.certificates.map((cert) => (
              <li key={cert.fingerprint_sha256} className="flex flex-col">
                <span>{cert.subject}</span>
                <span className="font-mono text-fg-muted">
                  SHA-256 {cert.fingerprint_sha256.slice(0, 23)}… · expires {formatWhen(cert.not_after)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ProviderDialog({
  open,
  onOpenChange,
  provider,
  writable,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  provider: ProviderOut | undefined;
  writable: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto">
        {open && (
          <ProviderFormBody
            provider={provider}
            writable={writable}
            onClose={() => {
              onOpenChange(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ProviderFormBody({
  provider: initial,
  writable,
  onClose,
}: {
  provider: ProviderOut | undefined;
  writable: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const [provider, setProvider] = useState(initial);
  const [form, setForm] = useState(() => formFrom(initial));
  const readOnly = !writable || provider?.managed_by === "config";
  const set =
    <K extends keyof ProviderForm>(key: K) =>
    (value: ProviderForm[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
    };
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: authListProvidersQueryKey() });
    await queryClient.invalidateQueries({ queryKey: authSignInOptionsQueryKey() });
  };
  const create = useMutation({
    ...withReauth(reauth, authCreateProviderMutation()),
    onSuccess: async (created) => {
      await invalidate();
      toast(`${created.display_name} added`);
      if (created.kind === "saml") {
        // The SP details only exist now: keep the dialog open so they can be copied into the IdP.
        setProvider(created);
        setForm(formFrom(created));
      } else onClose();
    },
  });
  const update = useMutation({
    ...withReauth(reauth, authUpdateProviderMutation()),
    onSuccess: async (updated) => {
      await invalidate();
      toast(`${updated.display_name} saved`);
      onClose();
    },
  });
  const error = create.error ?? update.error;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body = providerBody(form);
    if (provider) update.mutate({ path: { provider_id: provider.id }, body });
    else create.mutate({ body: { ...body, id: form.id.trim(), kind: form.kind } });
  };

  const title = provider
    ? readOnly
      ? provider.display_name
      : `Edit ${provider.display_name}`
    : "Add an identity provider";

  return (
    <form className="flex flex-col gap-4" onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>
          {provider?.managed_by === "config"
            ? "Defined in the server configuration: change it there."
            : form.kind === "saml"
              ? "SAML 2.0: import the IdP's metadata, or enter its entity ID, SSO URL and signing certificate."
              : "OpenID Connect: register Agnostic as an app in your IdP and paste its client ID and secret."}
        </DialogDescription>
      </DialogHeader>
      {provider && !initial && (
        <>
          <Callout tone="insight" title="Provider added">
            Finish the setup in your identity provider with these values, then test a sign-in.
          </Callout>
          <SpDetails provider={provider} />
        </>
      )}
      {!provider && (
        <SegmentedControl
          label="Protocol"
          value={form.kind}
          options={[
            { value: "oidc", label: "OIDC" },
            { value: "saml", label: "SAML 2.0" },
          ]}
          onValueChange={(value) => {
            setForm({ ...formFrom(undefined, value), id: form.id, displayName: form.displayName });
          }}
        />
      )}
      <fieldset disabled={readOnly} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="ID"
            hint="Lowercase slug, used in URLs."
            value={form.id}
            onChange={set("id")}
            required
            disabled={Boolean(provider)}
            placeholder={form.kind === "saml" ? "okta-saml" : "okta"}
          />
          <TextField
            label="Display name"
            mono={false}
            value={form.displayName}
            onChange={set("displayName")}
            placeholder="Okta"
          />
        </div>
        {form.kind === "oidc" ? (
          <>
            <Field label="Preset">
              {({ id }) => (
                <Select
                  value={form.preset}
                  onValueChange={(value) => {
                    setForm(withPreset(form, value as OidcPreset));
                  }}
                  disabled={readOnly}
                >
                  <SelectTrigger id={id} aria-label="Preset">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {OIDC_PRESETS.map((preset) => (
                      <SelectItem key={preset.value} value={preset.value}>
                        {preset.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
            {["oidc", "okta", "google"].includes(form.preset) && (
              <TextField
                label="Issuer"
                value={form.issuer}
                onChange={set("issuer")}
                placeholder="https://acme.okta.com"
                hint={
                  form.preset === "oidc"
                    ? "Keycloak: https://sso.example.com/realms/<realm>. Add a groups claim mapper to sync groups at sign-in."
                    : undefined
                }
              />
            )}
            {form.preset === "gitlab" && (
              <TextField
                label="GitLab URL"
                value={form.baseUrl}
                onChange={set("baseUrl")}
                placeholder="https://gitlab.com"
                hint={`Self-managed: the instance's external_url, which is also its issuer. Sign-in uses ${gitlabIssuer(form.baseUrl)}.`}
              />
            )}
            {form.preset === "github" && (
              <TextField
                label="GitHub Enterprise URL"
                value={form.baseUrl}
                onChange={set("baseUrl")}
                placeholder="https://github.com"
                hint="Only for GitHub Enterprise Server. Empty uses github.com."
              />
            )}
            <div className="grid grid-cols-2 gap-3">
              <TextField label="Client ID" value={form.clientId} onChange={set("clientId")} required />
              <TextField
                label="Client secret"
                type="password"
                value={form.clientSecret}
                onChange={set("clientSecret")}
                hint={provider?.oidc?.has_client_secret ? "Saved. Leave empty to keep it." : "Write-only."}
              />
            </div>
            <TextField
              label="Scopes"
              value={form.scopes}
              onChange={set("scopes")}
              placeholder="openid email profile"
              hint="Space-separated. Empty uses the preset's defaults."
            />
            {provider?.oidc && (
              <Field label="Redirect URI">
                {() => <CopyField label="Redirect URI" value={provider.oidc?.callback_url ?? ""} />}
              </Field>
            )}
          </>
        ) : (
          <>
            <SegmentedControl
              label="IdP metadata"
              value={form.samlSource}
              options={[
                { value: "url", label: "Metadata URL" },
                { value: "xml", label: "Paste XML" },
                { value: "manual", label: "Enter manually" },
              ]}
              onValueChange={set("samlSource")}
            />
            {form.samlSource === "url" && (
              <>
                <TextField
                  label="Metadata URL"
                  value={form.metadataUrl}
                  onChange={set("metadataUrl")}
                  required
                  placeholder="https://acme.okta.com/app/…/sso/saml/metadata"
                />
                {provider && (
                  <Switch
                    label="Fetch the metadata again"
                    description="Picks up rotated signing certificates."
                    checked={form.refreshMetadata}
                    onCheckedChange={set("refreshMetadata")}
                    disabled={readOnly}
                  />
                )}
              </>
            )}
            {form.samlSource === "xml" && (
              <Field
                label="Metadata XML"
                hint={provider ? "Paste new metadata to replace the saved one." : undefined}
              >
                {({ id, describedBy }) => (
                  <Textarea
                    id={id}
                    required
                    aria-describedby={describedBy}
                    value={form.metadataXml}
                    placeholder='<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" …'
                    onChange={(event) => {
                      set("metadataXml")(event.target.value);
                    }}
                  />
                )}
              </Field>
            )}
            {form.samlSource === "manual" && (
              <>
                <TextField
                  label="IdP entity ID"
                  value={form.idpEntityId}
                  onChange={set("idpEntityId")}
                  required
                />
                <TextField label="SSO URL" value={form.ssoUrl} onChange={set("ssoUrl")} required />
                <Field
                  label="Signing certificate (PEM)"
                  hint={provider ? "Leave empty to keep the saved certificates." : undefined}
                >
                  {({ id, describedBy }) => (
                    <Textarea
                      id={id}
                      required={!provider}
                      aria-describedby={describedBy}
                      value={form.certificate}
                      placeholder="-----BEGIN CERTIFICATE-----"
                      onChange={(event) => {
                        set("certificate")(event.target.value);
                      }}
                    />
                  )}
                </Field>
              </>
            )}
            <Field label="NameID format" hint="Empty uses the IdP's default (email address recommended).">
              {({ id, describedBy }) => (
                <>
                  <Input
                    id={id}
                    mono
                    list={`${id}-formats`}
                    aria-describedby={describedBy}
                    value={form.nameIdFormat}
                    onChange={(event) => {
                      set("nameIdFormat")(event.target.value);
                    }}
                  />
                  <datalist id={`${id}-formats`}>
                    {NAME_ID_FORMATS.map((format) => (
                      <option key={format} value={format} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1.5 text-[13px] font-medium text-fg-secondary">Attribute mapping</legend>
              <div className="grid grid-cols-3 gap-3">
                <TextField
                  label="Email attribute"
                  value={form.mapEmail}
                  onChange={set("mapEmail")}
                  placeholder="email"
                />
                <TextField
                  label="Name attribute"
                  value={form.mapName}
                  onChange={set("mapName")}
                  placeholder="displayName"
                />
                <TextField
                  label="Groups attribute"
                  value={form.mapGroups}
                  onChange={set("mapGroups")}
                  placeholder="groups"
                />
              </div>
            </fieldset>
          </>
        )}
        <TextField
          label="Allowed email domains"
          value={form.domains}
          onChange={set("domains")}
          placeholder="localhost.company"
          hint="Comma-separated. Empty allows invited people from any domain."
        />
        <Switch
          label="Create accounts on first sign-in"
          description="Just-in-time provisioning for people from the allowed domains (no invitation needed)."
          checked={form.jit}
          onCheckedChange={set("jit")}
          disabled={readOnly}
        />
        <Switch
          label="Trust unverified emails"
          description="Only for IdPs that don't send email_verified but own the domain."
          checked={form.trustUnverified}
          onCheckedChange={set("trustUnverified")}
          disabled={readOnly}
        />
        <Switch
          label="Enabled"
          description="Shown on the sign-in page."
          checked={form.enabled}
          onCheckedChange={set("enabled")}
          disabled={readOnly}
        />
      </fieldset>
      {provider && initial && <SpDetails provider={provider} />}
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          {readOnly || (provider && !initial) ? "Close" : "Cancel"}
        </Button>
        {!readOnly && (
          <Button type="submit" variant="primary" disabled={create.isPending || update.isPending}>
            {provider ? (create.isPending || update.isPending ? "Saving…" : "Save provider") : "Add provider"}
          </Button>
        )}
      </DialogFooter>
    </form>
  );
}

function ProvidersCard({ writable }: { writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const providers = useQuery(withQueryFn(authListProvidersOptions()));
  const [dialog, setDialog] = useState<{ provider: ProviderOut | undefined } | null>(null);
  const remove = useMutation({
    ...withReauth(reauth, authDeleteProviderMutation()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: authListProvidersQueryKey() });
      await queryClient.invalidateQueries({ queryKey: authSignInOptionsQueryKey() });
      toast("Provider removed");
    },
  });

  const columns: Column<ProviderOut>[] = [
    {
      id: "name",
      header: "Provider",
      cell: (row) => (
        <div className="flex flex-col">
          <span className="font-medium">{row.display_name}</span>
          <span className="font-mono text-[12px] text-fg-muted">{row.id}</span>
        </div>
      ),
    },
    {
      id: "kind",
      header: "Protocol",
      cell: (row) => (
        <span className="flex items-center gap-1.5">
          <Badge tone="outline">{row.kind === "saml" ? "SAML" : "OIDC"}</Badge>
          {row.kind === "oidc" && <span className="text-fg-secondary">{PRESET_LABELS[row.preset]}</span>}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => <StatusPill status={row.enabled ? "active" : "paused"} />,
    },
    {
      id: "managed",
      header: "Managed by",
      cell: (row) =>
        row.managed_by === "config" ? (
          <Badge tone="muted" title="Defined in the server configuration">
            Config · read only
          </Badge>
        ) : (
          <span className="text-fg-secondary">This page</span>
        ),
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <span className="inline-flex gap-1">
          <Button
            size="28"
            variant="ghost"
            onClick={() => {
              setDialog({ provider: row });
            }}
          >
            {row.managed_by === "config" || !writable ? "View" : "Edit"}
          </Button>
          {row.managed_by === "database" && writable && (
            <Button
              size="28"
              variant="destructive-text"
              aria-label={`Remove ${row.display_name}`}
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Remove ${row.display_name}? People can no longer sign in with it.`))
                  remove.mutate({ path: { provider_id: row.id } });
              }}
            >
              Remove
            </Button>
          )}
        </span>
      ),
    },
  ];

  return (
    <Section
      title="Identity providers"
      description="Single sign-on with OIDC or SAML 2.0. Okta, Microsoft Entra ID, Keycloak and Google Workspace support both."
      action={
        writable ? (
          <Button
            size="30"
            variant="primary"
            onClick={() => {
              setDialog({ provider: undefined });
            }}
          >
            Add provider
          </Button>
        ) : undefined
      }
    >
      {providers.isPending ? (
        <LoadingRows rows={2} label="Loading providers" />
      ) : providers.isError ? (
        <ErrorState reason={describeError(providers.error).reason} onRetry={() => void providers.refetch()} />
      ) : (
        <DataTable
          label="Identity providers"
          columns={columns}
          rows={providers.data}
          rowKey={(row) => row.id}
          empty={
            <p className="text-[13px] text-fg-muted">No providers yet: people sign in with a password.</p>
          }
        />
      )}
      {remove.error && <Callout tone="danger">{describeError(remove.error).reason}</Callout>}
      <ProviderDialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null);
        }}
        provider={dialog?.provider}
        writable={writable}
      />
    </Section>
  );
}

type PolicyForm = {
  enforceSso: boolean;
  breakGlass: string;
  idle: string;
  absolute: string;
  mfa: AuthPolicyOut["mfa_policy"];
};

function policyForm(policy: AuthPolicyOut): PolicyForm {
  return {
    enforceSso: policy.enforce_sso,
    breakGlass: policy.break_glass_user_id ?? "",
    idle: policy.session_idle_minutes === null ? "" : String(policy.session_idle_minutes),
    absolute: policy.session_absolute_hours === null ? "" : String(policy.session_absolute_hours),
    mfa: policy.mfa_policy,
  };
}

function PolicyCard({ policy, writable }: { policy: AuthPolicyOut; writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const members = useQuery(withQueryFn(membersListMembersOptions()));
  const owners = (members.data ?? []).filter((member) => member.org_role === "owner");
  const [form, setForm] = useState(() => policyForm(policy));
  const saved = policyForm(policy);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const save = useMutation({
    ...withReauth(reauth, authUpdatePolicyMutation()),
    onSuccess: (data) => {
      queryClient.setQueryData(authGetPolicyQueryKey(), data);
      setForm(policyForm(data));
      toast("Sign-in policy saved");
    },
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const body: AuthPolicyUpdate = {
      enforce_sso: form.enforceSso,
      break_glass_user_id: form.breakGlass === "" ? null : form.breakGlass,
      session_idle_minutes: optionalNumber(form.idle),
      session_absolute_hours: optionalNumber(form.absolute),
      mfa_policy: form.mfa,
    };
    save.mutate({ body });
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <Section
        title="Single sign-on enforcement"
        description="When on, everyone signs in through an identity provider. Passwords stop working except for one break-glass Owner, and every use of it is alerted."
      >
        <fieldset disabled={!writable} className="flex flex-col gap-4">
          <Switch
            label="Require SSO"
            description="Needs an enabled provider and a break-glass Owner who has a password."
            checked={form.enforceSso}
            disabled={!writable}
            onCheckedChange={(checked) => {
              setForm({ ...form, enforceSso: checked });
            }}
          />
          <Field
            label="Break-glass Owner"
            hint="Can still sign in with a password (and second factor) if the identity provider is down."
          >
            {({ id, describedBy }) => (
              <Select
                value={form.breakGlass === "" ? "__none__" : form.breakGlass}
                disabled={!writable}
                onValueChange={(value) => {
                  setForm({ ...form, breakGlass: value === "__none__" ? "" : value });
                }}
              >
                <SelectTrigger
                  id={id}
                  aria-label="Break-glass Owner"
                  aria-describedby={describedBy}
                  className="max-w-md"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Nobody</SelectItem>
                  {owners.map((owner) => (
                    <SelectItem key={owner.user_id} value={owner.user_id}>
                      {owner.display_name} · {owner.email}
                    </SelectItem>
                  ))}
                  {policy.break_glass_user &&
                    !owners.some((owner) => owner.user_id === policy.break_glass_user_id) && (
                      <SelectItem value={policy.break_glass_user.id}>
                        {policy.break_glass_user.display_name} · {policy.break_glass_user.email}
                      </SelectItem>
                    )}
                </SelectContent>
              </Select>
            )}
          </Field>
        </fieldset>
      </Section>
      <Section
        title="Sessions"
        description="How long a browser stays signed in. Empty uses the defaults; shorter limits apply at the next request."
      >
        <fieldset disabled={!writable} className="grid max-w-xl grid-cols-2 gap-3">
          <Field
            label="Idle timeout (minutes)"
            hint={`Default ${String(policy.default_session_idle_minutes)}.`}
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="number"
                min={5}
                inputMode="numeric"
                placeholder={String(policy.default_session_idle_minutes)}
                aria-describedby={describedBy}
                value={form.idle}
                onChange={(event) => {
                  setForm({ ...form, idle: event.target.value });
                }}
              />
            )}
          </Field>
          <Field
            label="Absolute lifetime (hours)"
            hint={`Default ${String(policy.default_session_absolute_hours)}.`}
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="number"
                min={1}
                inputMode="numeric"
                placeholder={String(policy.default_session_absolute_hours)}
                aria-describedby={describedBy}
                value={form.absolute}
                onChange={(event) => {
                  setForm({ ...form, absolute: event.target.value });
                }}
              />
            )}
          </Field>
        </fieldset>
      </Section>
      <Section
        title="Two-step verification"
        description="Second factors (authenticator app or security key) for email + password sign-ins. SSO sign-ins rely on the identity provider's MFA."
      >
        <fieldset disabled={!writable}>
          <RadioCards
            legend="MFA policy"
            value={form.mfa}
            options={MFA_OPTIONS}
            onValueChange={(value) => {
              setForm({ ...form, mfa: value });
            }}
          />
        </fieldset>
      </Section>
      {save.error && <Callout tone="danger">{describeError(save.error).reason}</Callout>}
      {writable && (
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save sign-in policy"}
          </Button>
          {dirty && (
            <Button
              variant="ghost"
              onClick={() => {
                setForm(saved);
                save.reset();
              }}
            >
              Discard
            </Button>
          )}
          {policy.updated_at && (
            <span className="text-[12px] text-fg-muted">Last changed {formatWhen(policy.updated_at)}</span>
          )}
        </div>
      )}
    </form>
  );
}

export function AuthenticationSection() {
  const { writable, note } = useWritable("settings:write");
  const policy = useQuery(withQueryFn(authGetPolicyOptions()));
  return (
    <div className="flex flex-col gap-5">
      {note}
      <ProvidersCard writable={writable} />
      {policy.isPending ? (
        <LoadingRows rows={4} label="Loading the sign-in policy" />
      ) : policy.isError ? (
        <ErrorState reason={describeError(policy.error).reason} onRetry={() => void policy.refetch()} />
      ) : (
        <PolicyCard key={policy.data.updated_at ?? "initial"} policy={policy.data} writable={writable} />
      )}
      <Facts
        rows={[
          [
            "Step-up",
            "Changes on this page ask you to confirm it's you if you haven't signed in within the last 10 minutes.",
          ],
        ]}
      />
    </div>
  );
}
