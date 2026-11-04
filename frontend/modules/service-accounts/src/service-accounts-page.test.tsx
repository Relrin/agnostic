import { API, sampleOrgHandlers, renderPage, serviceAccountsHandlers } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ServiceAccountsPage as Page } from "./service-accounts-page";

/** Tooltips need the provider the shell mounts. */
function ServiceAccountsPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

// The service-account handlers go first: they also answer /me/access with service_accounts:manage.
const handlers = () => [...serviceAccountsHandlers(), ...sampleOrgHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const PATH = "/access/service-accounts";

/** Records the JSON bodies posted to `url`, then lets the fixtures answer. */
function capture(url: string): unknown[] {
  const sent: unknown[] = [];
  server.use(
    http.post(url, async ({ request }) => {
      sent.push(await request.clone().json());
      return undefined;
    }),
  );
  return sent;
}

async function openCreate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "New service account" }));
  return screen.findByRole("form", { name: "New service account" });
}

describe("ServiceAccountsPage", () => {
  it("lists accounts with scopes, instances and expiry warnings", async () => {
    renderPage(ServiceAccountsPage, { path: PATH });
    const table = await screen.findByRole("table", { name: "Service accounts" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);

    const zendesk = within(table).getByText("sa:zendesk-bridge").closest("tr");
    expect(zendesk).not.toBeNull();
    const zendeskRow = within(zendesk as HTMLElement);
    expect(zendeskRow.getByText("Custom scopes")).toBeInTheDocument();
    expect(zendeskRow.getByText("privileged")).toBeInTheDocument();
    expect(zendeskRow.getByText("prod-agentos")).toBeInTheDocument();
    expect(zendeskRow.getByText("Dana Okafor")).toBeInTheDocument();
    expect(zendeskRow.getByText("No expiry")).toHaveClass("text-warning");

    const slack = within(within(table).getByText("sa:slack-bot").closest("tr") as HTMLElement);
    expect(slack.getByText("Access role: Viewer + 1 scope")).toBeInTheDocument();
    // Ten days left: under the two-week warning.
    expect(slack.getByText(/\d{4}$/)).toHaveClass("text-warning");

    const ci = within(within(table).getByText("sa:ci-evals").closest("tr") as HTMLElement);
    expect(ci.getByText("staging-agentos")).toBeInTheDocument();
    expect(ci.getByText(/\d{4}$/)).toHaveClass("text-fg-secondary");

    expect(screen.getByText(/Scoped service accounts can't resolve approvals/)).toBeInTheDocument();
    expect(screen.getByText("3 accounts · 4 active tokens")).toBeInTheDocument();
  });

  it("opens an account with its scopes, isolation note and tokens", async () => {
    const user = userEvent.setup();
    renderPage(ServiceAccountsPage, { path: PATH });
    await user.click(await screen.findByRole("button", { name: "zendesk-bridge" }));
    const aside = await screen.findByRole("complementary", { name: "Service account details" });
    expect(await within(aside).findByRole("heading", { name: "zendesk-bridge" })).toBeInTheDocument();
    expect(within(aside).getByText("agents:support-triage:run")).toBeInTheDocument();
    expect(within(aside).getByText("sessions:write")).toHaveClass("text-danger");
    expect(within(aside).getByText(/Sends user_id per request/)).toBeInTheDocument();

    const native = within(aside).getByRole("list", { name: "Native · per instance" });
    const active = within(native).getByRole("listitem", { name: "Token agno_pat_7Hq2" });
    expect(within(active).getByText("ACTIVE")).toBeInTheDocument();
    const revoked = within(native).getByRole("listitem", { name: "Token agno_pat_3Lw9" });
    expect(within(revoked).getByText("REVOKED")).toBeInTheDocument();
    expect(within(revoked).queryByRole("button", { name: /Rotate/ })).not.toBeInTheDocument();
    const gateway = within(aside).getByRole("list", { name: "Gateway" });
    expect(within(gateway).getByText(/from 10\.0\.4\.12/)).toBeInTheDocument();
  });

  it("creates a custom-scope account and shows each token once", async () => {
    const user = userEvent.setup();
    const sent = capture(`${API}/service-accounts`);
    renderPage(ServiceAccountsPage, { path: PATH });
    const form = await openCreate(user);

    await user.type(within(form).getByLabelText("Name"), "airflow-nightly");
    expect(within(form).getByText("sa:airflow-nightly")).toBeInTheDocument();
    await user.click(within(form).getByRole("checkbox", { name: "prod-agentos" }));
    await user.click(within(form).getByRole("checkbox", { name: "staging-agentos" }));
    await user.click(await within(form).findByRole("checkbox", { name: "agents:read" }));
    await user.click(within(form).getByRole("checkbox", { name: "sessions:read" }));
    await user.type(within(form).getByLabelText("One component's scope"), "agents:support-triage:run{Enter}");
    expect(within(form).getByRole("list", { name: "Per-component scopes" })).toHaveTextContent(
      "agents:support-triage:run",
    );
    await user.click(within(form).getByRole("checkbox", { name: /^Gateway/ }));
    expect(within(form).queryByRole("alert")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(
        within(form).getByText(/--scopes agents:read,sessions:read,agents:support-triage:run/),
      ).toBeVisible();
    });
    expect(within(form).getByText(/--kind gateway/)).toBeInTheDocument();

    await user.click(within(form).getByRole("button", { name: "Create and show tokens" }));
    const shown = await screen.findByRole("region", { name: "New tokens" });
    expect(sent).toEqual([
      {
        name: "airflow-nightly",
        instances: ["ins_01M6A0EEZEQ373S26F2014PRD", "ins_01M6A0EEZEQ373S26F2014STG"],
        role_id: null,
        scopes: ["agents:read", "sessions:read", "agents:support-triage:run"],
        expires_in: "90d",
        kinds: ["native", "gateway"],
        forwards_user_id: false,
        confirm_privileged: false,
      },
    ]);

    expect(within(shown).getByText("sa:airflow-nightly created")).toBeInTheDocument();
    expect(within(shown).getByText("They won't be shown again")).toBeInTheDocument();
    expect(within(shown).getByText("Native · prod-agentos")).toBeInTheDocument();
    expect(within(shown).getByText("Native · staging-agentos")).toBeInTheDocument();
    expect(within(shown).getByText("Gateway")).toBeInTheDocument();
    expect(within(shown).getAllByText(/^agno_pat_\w{32}$/)).toHaveLength(2);
    expect(within(shown).getAllByText(/^agn_pat_\w{32}$/)).toHaveLength(1);
    expect(within(shown).getAllByText(/Authorization: Bearer \$AGNO_PAT/)).toHaveLength(3);

    await user.click(within(shown).getByRole("button", { name: "I've stored it" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "New tokens" })).not.toBeInTheDocument();
    });
    const aside = await screen.findByRole("complementary", { name: "Service account details" });
    expect(await within(aside).findByRole("heading", { name: "airflow-nightly" })).toBeInTheDocument();
  });

  it("needs an explicit confirmation for privileged scopes", async () => {
    const user = userEvent.setup();
    const sent = capture(`${API}/service-accounts`);
    renderPage(ServiceAccountsPage, { path: PATH });
    const form = await openCreate(user);
    await user.type(within(form).getByLabelText("Name"), "token-minter");
    await user.click(within(form).getByRole("checkbox", { name: "prod-agentos" }));
    await user.click(await within(form).findByRole("checkbox", { name: "service_accounts:write" }));

    const alert = within(form).getByRole("alert");
    expect(alert).toHaveTextContent("Privileged scopes");
    expect(alert).toHaveTextContent("service_accounts:write lets this token mint new tokens.");
    const submit = within(form).getByRole("button", { name: "Create and show token" });
    expect(submit).toBeDisabled();
    await waitFor(() => {
      expect(within(form).getByText(/--yes-privileged/)).toBeInTheDocument();
    });

    await user.click(within(form).getByLabelText("I understand this account gets privileged scopes"));
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(await screen.findByRole("region", { name: "New tokens" })).toBeInTheDocument();
    expect(sent).toEqual([
      expect.objectContaining({ scopes: ["service_accounts:write"], confirm_privileged: true }),
    ]);
  });

  it("asks for the confirmation when the server flags a privileged scope", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API}/service-accounts`, async ({ request }) => {
        const body = (await request.clone().json()) as { confirm_privileged?: boolean };
        if (body.confirm_privileged) return undefined;
        return HttpResponse.json(
          {
            type: "about:blank",
            status: 422,
            code: "privileged_confirmation_required",
            title: "Privileged scopes need an explicit confirmation",
            privileged_scopes: ["agents:read"],
          },
          { status: 422 },
        );
      }),
    );
    renderPage(ServiceAccountsPage, { path: PATH });
    const form = await openCreate(user);
    await user.type(within(form).getByLabelText("Name"), "reader");
    await user.click(within(form).getByRole("checkbox", { name: "prod-agentos" }));
    await user.click(await within(form).findByRole("checkbox", { name: "agents:read" }));
    const submit = within(form).getByRole("button", { name: "Create and show token" });
    await user.click(submit);

    expect(await within(form).findByRole("alert")).toHaveTextContent("agents:read");
    expect(submit).toBeDisabled();
    await user.click(within(form).getByLabelText("I understand this account gets privileged scopes"));
    await user.click(submit);
    expect(await screen.findByRole("region", { name: "New tokens" })).toBeInTheDocument();
  });

  it("rotates a gateway token and keeps the old one for 24 h", async () => {
    const user = userEvent.setup();
    const sent = capture(`${API}/service-accounts/:account/tokens`);
    renderPage(ServiceAccountsPage, { path: PATH, url: `${PATH}?account=zendesk-bridge` });
    const aside = await screen.findByRole("complementary", { name: "Service account details" });
    await user.click(await within(aside).findByRole("button", { name: "Rotate agn_pat_Qm4x" }));

    const dialog = await screen.findByRole("dialog", { name: "Rotate agn_pat_Qm4x…?" });
    expect(dialog).toHaveTextContent("the old one keeps working for 24 h");
    await user.click(within(dialog).getByRole("button", { name: "Rotate token" }));

    expect(await within(dialog).findByRole("heading", { name: "Copy the token now" })).toBeInTheDocument();
    expect(sent).toEqual([{ kind: "gateway" }]);
    expect(within(dialog).getByText("sa:zendesk-bridge token rotated")).toBeInTheDocument();
    expect(within(dialog).getByText(/^agn_pat_\w{32}$/)).toBeInTheDocument();
    expect(within(dialog).getByText(/The old token keeps working until/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "I've stored it" }));

    const gateway = within(aside).getByRole("list", { name: "Gateway" });
    const old = within(gateway).getByRole("listitem", { name: "Token agn_pat_Qm4x" });
    expect(within(old).getByText("ROTATING OUT")).toBeInTheDocument();
    expect(within(old).getByRole("button", { name: "Revoke agn_pat_Qm4x" })).toHaveTextContent("Revoke now");
    expect(within(gateway).getAllByRole("listitem")).toHaveLength(2);
  });

  it("revokes a native token after a confirmation", async () => {
    const user = userEvent.setup();
    renderPage(ServiceAccountsPage, { path: PATH, url: `${PATH}?account=ci-evals` });
    const aside = await screen.findByRole("complementary", { name: "Service account details" });
    await user.click(await within(aside).findByRole("button", { name: "Revoke agno_pat_K2c8" }));
    await user.click(within(aside).getByRole("button", { name: "Revoke agno_pat_K2c8…" }));
    const card = within(aside).getByRole("listitem", { name: "Token agno_pat_K2c8" });
    expect(await within(card).findByText("REVOKED")).toBeInTheDocument();
    // With no active native token on staging, a new one can be issued.
    expect(within(aside).getByRole("button", { name: "Issue token" })).toBeInTheDocument();
  });

  it("explains a step-up when the change needs a recent sign-in", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${API}/service-accounts/:account/tokens`, () =>
        HttpResponse.json(
          { type: "about:blank", status: 403, code: "reauth_required", title: "Confirm it's you" },
          { status: 403 },
        ),
      ),
    );
    renderPage(ServiceAccountsPage, { path: PATH, url: `${PATH}?account=zendesk-bridge` });
    const aside = await screen.findByRole("complementary", { name: "Service account details" });
    await user.click(await within(aside).findByRole("button", { name: "Rotate agno_pat_7Hq2" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("callers see a brief gap");
    await user.click(within(dialog).getByRole("button", { name: "Rotate token" }));
    const notice = await within(dialog).findByRole("alert");
    expect(notice).toHaveTextContent("Confirm it's you");
    expect(within(notice).getByRole("link", { name: "Sign in again" })).toHaveAttribute(
      "href",
      expect.stringContaining("/login?next="),
    );
  });

  it("deletes an account", async () => {
    const user = userEvent.setup();
    renderPage(ServiceAccountsPage, { path: PATH, url: `${PATH}?account=slack-bot` });
    const aside = await screen.findByRole("complementary", { name: "Service account details" });
    await user.click(await within(aside).findByRole("button", { name: "Delete account" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete sa:slack-bot?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete account" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("complementary", { name: "Service account details" }),
      ).not.toBeInTheDocument();
    });
    const table = screen.getByRole("table", { name: "Service accounts" });
    await waitFor(() => {
      expect(within(table).queryByText("sa:slack-bot")).not.toBeInTheDocument();
    });
  });
});
