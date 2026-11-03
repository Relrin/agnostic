import { API, notificationsHandlers, p01Handlers, renderWithProviders } from "@agnostic/testing";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { NotificationPreferences } from "./notification-preferences";

const handlers = () => [...p01Handlers(), ...notificationsHandlers()];
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

describe("NotificationPreferences", () => {
  it("turns Slack on for approval requests", async () => {
    let sent: unknown;
    server.use(
      http.put(`${API}/me/notification-preferences`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ events: [], quiet_hours: null, slack_available: true });
      }),
    );
    renderWithProviders(<NotificationPreferences />);
    const slack = await screen.findByRole("checkbox", { name: "Approval requested by Slack" });
    expect(slack).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Approval requested by In app" })).toBeChecked();
    await userEvent.setup().click(slack);
    await screen.findByText("Quiet hours");
    expect(sent).toEqual({ events: { "approval.created": ["in_app", "slack"] } });
  });
});
