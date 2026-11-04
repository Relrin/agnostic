import { API, contextHandlers, sampleOrgHandlers, operateHandlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { LearningsPage as Page } from "./learnings-page";

/** Tooltips need the provider the shell mounts. */
function LearningsPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...contextHandlers(), ...sampleOrgHandlers(), ...operateHandlers()];
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

describe("LearningsPage", () => {
  it("shows type tabs with counts and a readable record", async () => {
    renderPage(LearningsPage, { path: "/i/$instance/learnings", url: "/i/prod-agentos/learnings" });
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /session_context/ })).toHaveTextContent("1,406");
    });
    const record = await screen.findByRole("region", { name: "Record" });
    expect(within(record).getByRole("heading", { name: "user_profile_cus_48213" })).toBeInTheDocument();
    expect(within(record).getByText("Preferred channel")).toBeInTheDocument();
    expect(within(record).getByText("Deterministic id: user_profile_{user_id}")).toBeInTheDocument();
  });

  it("enables per-user deletion only once the user id is typed", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.post(`${API}/instances/:instance/learnings/delete-user`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          instance_id: "i",
          instance: "prod-agentos",
          user_id: "cus_48213",
          learning_type: null,
          deleted: 3,
        });
      }),
    );
    renderPage(LearningsPage, { path: "/i/$instance/learnings", url: "/i/prod-agentos/learnings" });
    const region = await screen.findByRole("region", { name: "Delete learnings for cus_48213" });
    const button = within(region).getByRole("button", { name: "Delete all" });
    expect(button).toBeDisabled();
    const confirm = within(region).getByRole("textbox", { name: "Confirmation" });
    await user.type(confirm, "cus_4821");
    expect(button).toBeDisabled();
    await user.type(confirm, "3");
    await user.click(button);
    await waitFor(() => {
      expect(sent).toEqual({ user_id: "cus_48213", learning_type: null, confirm: "cus_48213" });
    });
  });

  it("runs a data subject request across instances", async () => {
    const user = userEvent.setup();
    renderPage(LearningsPage, { path: "/i/$instance/learnings", url: "/i/prod-agentos/learnings" });
    await user.click(await screen.findByRole("button", { name: "Data subject request" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByRole("textbox", { name: "user_id" }), "cus_48213");
    await user.type(within(dialog).getByRole("textbox", { name: "Confirmation" }), "cus_48213");
    await user.click(within(dialog).getByRole("button", { name: "Delete on every instance" }));
    const results = await within(dialog).findByRole("list", { name: "Result per instance" });
    expect(within(results).getByText("Deleted 4 records")).toBeInTheDocument();
    expect(within(results).getByText(/Skipped: You don't have learnings:delete here./)).toBeInTheDocument();
  });
});
