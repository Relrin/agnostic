import { API, MARCUS, p01Handlers, PROD, renderPage } from "@agnostic/testing";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { PeoplePage } from "./people-page";

const server = setupServer(...p01Handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...p01Handlers());
});
afterAll(() => {
  server.close();
});

describe("PeoplePage", () => {
  it("lists members with org roles and access per instance", async () => {
    renderPage(PeoplePage, { path: "/access/people" });
    const marcus = (await screen.findByRole("button", { name: "Marcus Chen" })).closest("tr");
    if (!marcus) throw new Error("Marcus's row is missing");
    expect(within(marcus).getByText("Member")).toBeInTheDocument();
    expect(within(marcus).getByText("Operator")).toBeInTheDocument();
    expect(within(marcus).getByText("prod-agentos")).toBeInTheDocument();
    const daniel = screen.getByRole("button", { name: "Daniel Okafor" }).closest("tr");
    if (!daniel) throw new Error("Daniel's row is missing");
    expect(within(daniel).getByText("Full access")).toBeInTheDocument();
  });

  it("checks a permission with an explanation", async () => {
    let asked: unknown;
    server.use(
      http.post(`${API}/access/explain`, async ({ request }) => {
        asked = await request.json();
        return HttpResponse.json({
          allowed: false,
          scope: "components:write",
          instance_id: PROD,
          granted_by: [],
          missing_scopes: ["components:write"],
          alternatives: [{ kind: "role", label: "Builder", role_name: null }],
          explanation:
            "Needs `components:write` on prod-agentos. Marcus Chen has Operator there, which doesn't include it.",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: "/access/people" });
    await user.click(await screen.findByRole("button", { name: "Marcus Chen" }));
    await user.type(screen.getByLabelText("Scope to check for Marcus Chen"), "components:write");
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/which doesn't include it/)).toBeInTheDocument();
    expect(screen.getByLabelText("Not allowed")).toBeInTheDocument();
    expect(asked).toEqual({ user_id: MARCUS, scope: "components:write", instance: PROD });
  });

  it("invites someone and shows the link to share", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API}/invitations`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          {
            invitation: {
              id: "inv_1",
              email: "omar@localhost.company",
              org_role: "member",
              bindings: [],
              access_ends_at: null,
              invited_by: "usr_dana",
              expires_at: "2026-11-08T09:00:00Z",
              status: "pending",
              created_at: "2026-11-01T09:00:00Z",
            },
            accept_url: "http://agnostic.test/invite/tok",
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: "/access/people" });
    await user.click(await screen.findByRole("button", { name: "Invite people" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Email"), "omar@localhost.company");
    await user.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("http://agnostic.test/invite/tok")).toBeInTheDocument();
    expect(sent).toMatchObject({ email: "omar@localhost.company", org_role: "member", bindings: [] });
  });
});
