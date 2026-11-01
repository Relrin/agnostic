import { API, p01Handlers, renderPage } from "@agnostic/testing";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AuditPage } from "./audit-page";

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

describe("AuditPage", () => {
  it("lists events and explains a denial", async () => {
    const user = userEvent.setup();
    renderPage(AuditPage, { path: "/access/audit" });
    const denied = await screen.findByRole("button", { name: /was denied DELETE \/sessions\/x/ });
    expect(screen.getByText("members.update")).toBeInTheDocument();
    await user.click(denied);
    expect(await screen.findByText("Why it was denied")).toBeInTheDocument();
    expect(screen.getAllByText("sessions:delete").length).toBeGreaterThan(0);
  });

  it("filters by action", async () => {
    const seen: string[] = [];
    server.use(
      http.get(`${API}/audit/events`, ({ request }) => {
        seen.push(new URL(request.url).search);
        return HttpResponse.json({ data: [], next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderPage(AuditPage, { path: "/access/audit" });
    await user.type(await screen.findByLabelText("Filter by action"), "gateway.*");
    expect(await screen.findByText("No events match")).toBeInTheDocument();
    expect(seen.at(-1)).toContain("action=gateway.*");
  });
});
