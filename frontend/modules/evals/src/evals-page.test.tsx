import { API, observeHandlers, p01Handlers, p02Handlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { EvalsPage as Page } from "./evals-page";
import { casesNote } from "./labels";

/** Tooltips need the provider the shell mounts. */
function EvalsPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...p01Handlers(), ...p02Handlers(), ...observeHandlers()];
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

const URL = "/i/prod-agentos/evals?evaluation=evb_v4";

describe("EvalsPage", () => {
  it("compares the draft with the current version case by case", async () => {
    renderPage(EvalsPage, { path: "/i/$instance/evals", url: URL });
    const runs = await screen.findByRole("table", { name: "Eval runs" });
    expect(await within(runs).findByText("7.20 avg")).toHaveClass("text-danger");
    expect(within(runs).getByText(/run outside Agnostic/)).toBeInTheDocument();

    const stats = await screen.findByRole("table", { name: "Score statistics" });
    expect(within(stats).getByText("v3")).toBeInTheDocument();
    expect(within(stats).getAllByText("7.20")[0]).toHaveClass("text-danger"); // the regressed average
    expect(screen.getByText("Showing 5 of 5 · v3 → v4 draft · below 7: 1 → 2")).toBeInTheDocument();
    const cases = screen.getByRole("table", { name: "Cases" });
    expect(within(cases).getByText("9 → 3")).toBeInTheDocument();
    expect(within(cases).getByText("6 → 10")).toHaveClass("text-accent");
    expect(
      screen.getByText("v4 draft fixes case 5 but regresses cases 2 and 3 (9 → 3, 10 → 4) compared with v3."),
    ).toBeInTheDocument();
    expect(screen.getByText("v4 draft (7.20) would be blocked from publishing.")).toBeInTheDocument();
  });

  it("shows one version at a time", async () => {
    const user = userEvent.setup();
    renderPage(EvalsPage, { path: "/i/$instance/evals", url: URL });
    await user.click(await screen.findByRole("radio", { name: "v4 draft" }));
    const stats = screen.getByRole("table", { name: "Score statistics" });
    expect(within(stats).queryByText("v3")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 5 of 5 · 2 below 7 in v4 draft")).toBeInTheDocument();
  });

  it("switches the publish gate off", async () => {
    const user = userEvent.setup();
    let body: unknown;
    server.use(
      http.put(`${API}/instances/:instance/eval-gates`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          consequence: "Off: Publish ignores this eval.",
          state: "off",
          enabled: false,
        });
      }),
      http.get(`${API}/instances/:instance/eval-gates`, () => HttpResponse.json([])),
    );
    renderPage(EvalsPage, { path: "/i/$instance/evals", url: URL });
    const toggle = await screen.findByRole("switch", { name: "Gate publish on this eval" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    await waitFor(() => {
      expect(body).toMatchObject({
        component_id: "support-triage",
        dataset_id: "ds_billing",
        enabled: true,
        min_average: 8.5,
      });
    });
  });

  it("opens the new evaluation panel with the cost preview", async () => {
    const user = userEvent.setup();
    renderPage(EvalsPage, { path: "/i/$instance/evals", url: "/i/prod-agentos/evals" });
    await user.click(await screen.findByRole("button", { name: "Run evaluation" }));
    const panel = await screen.findByRole("region", { name: "New evaluation" });
    expect(await within(panel).findByText(/5 runs of the current version/)).toBeInTheDocument();
    expect(within(panel).getByRole("radio", { name: /Agent as judge/ })).toBeInTheDocument();
    expect(within(panel).getByText("POST /agnostic/v1/evals/run")).toBeInTheDocument();
  });

  it("words the cases note", () => {
    expect(casesNote(5, 25, { after: "v3" }, { after: 1 })).toBe("Showing 5 of 25 · 1 below 7 in v3");
  });
});
