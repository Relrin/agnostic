import { ReauthProvider } from "@agnostic/core";
import {
  API,
  assistantCalls,
  assistantHandlers,
  orgSettingsHandlers,
  sampleOrgHandlers,
  renderPage,
} from "@agnostic/testing";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { OrgSettingsPage } from "./org-settings-page";

const handlers = () => [...orgSettingsHandlers(), ...sampleOrgHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  // jsdom has no pointer capture or layout; Radix selects ask for both.
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => undefined;
  Element.prototype.releasePointerCapture = () => undefined;
  Element.prototype.scrollIntoView = () => undefined;
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

function Page() {
  return (
    <ReauthProvider>
      <OrgSettingsPage />
    </ReauthProvider>
  );
}

function open(section?: string) {
  return renderPage(Page, {
    path: section ? "/org/settings/$section" : "/org/settings",
    url: section ? `/org/settings/${section}` : "/org/settings",
  });
}

/** Records the JSON bodies sent to `method url`; the stateful fixtures still answer. */
function capture(method: "post" | "put" | "patch", url: string) {
  const bodies: unknown[] = [];
  server.use(
    http[method](url, async ({ request }) => {
      bodies.push(await request.clone().json());
      return undefined;
    }),
  );
  return bodies;
}

async function choose(user: ReturnType<typeof userEvent.setup>, trigger: HTMLElement, option: string) {
  await user.click(trigger);
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("OrgSettingsPage", () => {
  it("shows providers (config ones read only) and the sign-in policy", async () => {
    open();
    const table = await screen.findByRole("table", { name: "Identity providers" });
    expect(within(table).getByText("github")).toBeInTheDocument();
    expect(within(table).getByText("Config · read only")).toBeInTheDocument();
    expect(within(table).getByText("okta-saml")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "View" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Remove Okta" })).toBeInTheDocument();
    expect(await screen.findByRole("switch", { name: "Require SSO" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /Optional/ })).toBeChecked();
  });

  it("switches sections through the URL", async () => {
    const user = userEvent.setup();
    open("authentication");
    await user.click(await screen.findByRole("tab", { name: "Directory sync" }));
    expect(await screen.findByText("Okta SCIM · synced 4 min ago")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "SCIM base URL" })).toHaveValue(
      "http://agnostic.test/scim/v2",
    );
    expect(await screen.findByText("eng-platform")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "SIEM streaming" }));
    expect(await screen.findByText("Splunk HEC")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Audit retention & archive" }));
    expect(await screen.findByRole("button", { name: "Restore 2025-08 for search" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Temporary access" }));
    expect(await screen.findByLabelText("Longest temporary access (hours)")).toHaveValue(168);
  });

  it("hides AI features unless the assistant module is installed", async () => {
    open("ai-features");
    expect(await screen.findByRole("tab", { name: "Authentication" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "AI features" })).not.toBeInTheDocument();
  });

  it("configures AI features: provider, budget and redaction, the key write-only", async () => {
    const calls = assistantCalls();
    server.use(...assistantHandlers(calls));
    const user = userEvent.setup();
    open("ai-features");
    expect(await screen.findByRole("tab", { name: "AI features" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByLabelText("Model")).toHaveValue("qwen3:8b");
    expect(screen.getByLabelText("Endpoint")).toHaveValue("http://ollama.internal:11434");
    expect(screen.getByText(/What leaves the control plane/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("The model answered in 420 ms: 'ready'")).toBeInTheDocument();

    await user.type(screen.getByLabelText("API key"), "sk-local");
    await user.click(screen.getByRole("switch", { name: /Leave out tool arguments/ }));
    await user.clear(screen.getByLabelText("Tokens per person per month"));
    await user.type(screen.getByLabelText("Tokens per person per month"), "200000");
    await user.click(screen.getByRole("button", { name: "Save AI features" }));
    await waitFor(() => {
      expect(calls.settings).toHaveLength(1);
    });
    expect(calls.settings[0]).toMatchObject({
      enabled: true,
      models: { assistant: "ollama:qwen3:8b", summaries: "", suggestions: "" },
      api_key: "sk-local",
      redact_tool_args: true,
      redact_user_messages: true,
      user_monthly_tokens: 200000,
      monthly_token_budget: 5000000,
      version: 3,
    });
  });

  it("adds a SAML provider after a step-up and shows what to copy into the IdP", async () => {
    let attempts = 0;
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/auth/admin/providers`, async ({ request }) => {
        attempts += 1;
        bodies.push(await request.clone().json());
        if (attempts === 1)
          return HttpResponse.json(
            {
              type: "x",
              title: "Confirm it's you",
              status: 403,
              code: "reauth_required",
              reauth_window_seconds: 600,
            },
            { status: 403 },
          );
        return undefined;
      }),
    );
    const user = userEvent.setup();
    open("authentication");
    await user.click(await screen.findByRole("button", { name: "Add provider" }));
    const dialog = await screen.findByRole("dialog", { name: "Add an identity provider" });
    await user.click(within(dialog).getByRole("radio", { name: "SAML 2.0" }));
    await user.type(within(dialog).getByLabelText("ID"), "entra");
    await user.type(within(dialog).getByLabelText("Display name"), "Entra ID");
    await user.type(
      within(dialog).getByLabelText("Metadata URL"),
      "https://login.microsoftonline.com/tenant/federationmetadata/2007-06/federationmetadata.xml",
    );
    await user.type(within(dialog).getByLabelText("Email attribute"), "email");
    await user.type(within(dialog).getByLabelText("Groups attribute"), "groups");
    await user.type(within(dialog).getByLabelText("Allowed email domains"), "localhost.company");
    await user.click(within(dialog).getByRole("button", { name: "Add provider" }));

    const confirm = await screen.findByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(confirm).getByLabelText("Password"), "correct horse");
    await user.click(within(confirm).getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("textbox", { name: "ACS URL" })).toHaveValue(
      "http://agnostic.test/api/v1/auth/sso/entra/acs",
    );
    expect(screen.getByRole("textbox", { name: "SP entity ID" })).toHaveValue(
      "http://agnostic.test/api/v1/auth/sso/entra/metadata",
    );
    expect(screen.getByRole("link", { name: "Download SP metadata" })).toHaveAttribute(
      "href",
      "http://agnostic.test/api/v1/auth/admin/providers/entra/saml-metadata",
    );
    expect(attempts).toBe(2);
    expect(bodies[1]).toEqual({
      id: "entra",
      kind: "saml",
      preset: "saml",
      display_name: "Entra ID",
      enabled: true,
      allowed_email_domains: ["localhost.company"],
      jit_provisioning: false,
      trust_unverified_email: false,
      metadata_url:
        "https://login.microsoftonline.com/tenant/federationmetadata/2007-06/federationmetadata.xml",
      attribute_mapping: { email: "email", name: null, groups: "groups" },
    });
  });

  it("shows a new SCIM token once", async () => {
    const user = userEvent.setup();
    open("directory");
    await user.type(await screen.findByLabelText("New token label"), "Entra ID");
    await user.click(screen.getByRole("button", { name: "Create token" }));
    const dialog = await screen.findByRole("dialog", { name: "SCIM token · Entra ID" });
    expect(within(dialog).getByText("agn_scim_2xx_s3cr3tVALUE")).toBeInTheDocument();
    expect(within(dialog).getByText(/It won't be shown again/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.queryByText("agn_scim_2xx_s3cr3tVALUE")).not.toBeInTheDocument();
    });
    const table = screen.getByRole("table", { name: "SCIM tokens" });
    expect(await within(table).findByText("Entra ID")).toBeInTheDocument();
  });

  it("explains the 24 hour grace period when rotating", async () => {
    const user = userEvent.setup();
    open("directory");
    await user.click(await screen.findByRole("button", { name: "Rotate Okta SCIM" }));
    const dialog = await screen.findByRole("dialog", { name: "New SCIM token · Okta SCIM" });
    expect(within(dialog).getByText(/keeps working for 24 hours/)).toBeInTheDocument();
  });

  it("adds a webhook sink with an HMAC secret", async () => {
    const bodies = capture("post", `${API}/audit/sinks`);
    const user = userEvent.setup();
    open("siem");
    await user.click(await screen.findByRole("button", { name: "Add destination" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a SIEM destination" });
    await user.type(within(dialog).getByLabelText("Name"), "Datadog");
    await user.click(within(dialog).getByRole("radio", { name: "OCSF" }));
    await user.type(
      within(dialog).getByLabelText("URL"),
      "https://http-intake.logs.datadoghq.eu/api/v2/logs",
    );
    await user.type(within(dialog).getByLabelText("Signing secret"), "whsec_abc");
    expect(within(dialog).getByText(/X-Agnostic-Signature/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Headers"), "DD-API-KEY: dd_123");
    await user.click(within(dialog).getByRole("button", { name: "Add destination" }));
    expect(await screen.findByText("Datadog")).toBeInTheDocument();
    expect(bodies[0]).toEqual({
      name: "Datadog",
      kind: "https_webhook",
      format: "ocsf",
      enabled: true,
      config: {
        url: "https://http-intake.logs.datadoghq.eu/api/v2/logs",
        secret: "whsec_abc",
        headers: { "DD-API-KEY": "dd_123" },
      },
    });
  });

  it("sends a test event and shows the result", async () => {
    const user = userEvent.setup();
    open("siem");
    await user.click(await screen.findByRole("button", { name: "Send a test event to Splunk HEC" }));
    expect(await screen.findByText("Test event delivered")).toBeInTheDocument();
    expect(screen.getByText("HTTP 200 · 87 ms")).toBeInTheDocument();
  });

  it("saves the retention window without resending the saved secret", async () => {
    const bodies = capture("put", `${API}/audit/policy`);
    const user = userEvent.setup();
    open("audit-retention");
    const days = await screen.findByLabelText("Keep events for (days)");
    await user.clear(days);
    await user.type(days, "365");
    await user.click(screen.getByRole("radio", { name: /Compliance/ }));
    await user.click(screen.getByRole("button", { name: "Save retention" }));
    await waitFor(() => {
      expect(bodies).toHaveLength(1);
    });
    expect(bodies[0]).toEqual({
      hot_retention_days: 365,
      archive_enabled: true,
      endpoint: "https://minio.internal:9000",
      bucket: "agnostic-audit",
      prefix: "audit/",
      region: "us-east-1",
      access_key_id: "AKIAAGNOSTIC",
      object_lock_mode: "compliance",
      archive_retention_days: null,
      hash_chain: true,
    });
  });

  it("restores an archived month for search", async () => {
    const user = userEvent.setup();
    open("audit-retention");
    await user.click(await screen.findByRole("button", { name: "Restore 2025-08 for search" }));
    expect(await screen.findByText(/Searchable until/)).toBeInTheDocument();
  });

  it("saves the MFA policy and break-glass owner", async () => {
    const bodies = capture("put", `${API}/auth/admin/policy`);
    const user = userEvent.setup();
    open();
    await choose(
      user,
      await screen.findByRole("combobox", { name: "Break-glass Owner" }),
      "Daniel Okafor · daniel@localhost.company",
    );
    await user.click(screen.getByRole("radio", { name: /Required for admins/ }));
    await user.click(screen.getByRole("button", { name: "Save sign-in policy" }));
    await waitFor(() => {
      expect(bodies).toHaveLength(1);
    });
    expect(bodies[0]).toMatchObject({
      enforce_sso: false,
      break_glass_user_id: "usr_01M6A0EEZEQ373S26F20142DAN",
      mfa_policy: "required_admins",
      session_idle_minutes: null,
    });
  });
});
