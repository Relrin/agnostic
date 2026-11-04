import { API, observeHandlers, sampleOrgHandlers, operateHandlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { MetricsPage as Page, peakLow, presetRange } from "./metrics-page";

/** Tooltips need the provider the shell mounts. */
function MetricsPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...sampleOrgHandlers(), ...operateHandlers(), ...observeHandlers()];
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

describe("MetricsPage", () => {
  it("shows totals, the estimated cost from the price table and the per-component table", async () => {
    renderPage(MetricsPage, { path: "/i/$instance/metrics", url: "/i/prod-agentos/metrics" });
    const totals = await screen.findByRole("region", { name: "Totals" });
    expect(await within(totals).findByText("4,912")).toBeInTheDocument();
    expect(within(totals).getByText("2,908 agent · 288 team · 1,716 workflow")).toBeInTheDocument();
    expect(within(totals).getByText("3.8 runs per session")).toBeInTheDocument();
    // support-triage 26 + 27.5; ticket-router haiku 6.5 + opus 4.5 (gpt has no price yet).
    expect(within(totals).getByText("$64.50")).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "By component" });
    expect(within(table).getByText("+2")).toBeInTheDocument();
    expect(within(table).getByText("≈ $11.00")).toBeInTheDocument();
    expect(screen.getByText(/No price yet for gpt-6.1-sol/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      expect.stringContaining("/metrics/export.csv?from="),
    );
    expect(screen.getByText(/^Aggregated .+ ago$/)).toBeInTheDocument();
  });

  it("recomputes costs as prices change and saves the table", async () => {
    const user = userEvent.setup();
    let saved: unknown;
    server.use(
      http.put(`${API}/instances/:instance/price-table`, async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ prices: [] });
      }),
    );
    renderPage(MetricsPage, { path: "/i/$instance/metrics", url: "/i/prod-agentos/metrics" });
    const input = await screen.findByRole("spinbutton", { name: "claude-opus-5-5 input price" });
    await user.clear(input);
    await user.type(input, "10");
    // opus input doubles: support-triage 52 + 27.5, ticket-router 6.5 + 4 + 2.5.
    expect(await screen.findByText("$92.50")).toBeInTheDocument();
    await waitFor(
      () => {
        const body = saved as { prices: { model_id: string; input_per_1m: number }[] } | undefined;
        expect(body?.prices.find((row) => row.model_id === "claude-opus-5-5")?.input_per_1m).toBe(10);
      },
      { timeout: 2_000 },
    );
  });

  it("captions peaks and builds ranges", () => {
    expect(
      peakLow([
        { date: "2026-10-26", total: 2_000_000 },
        { date: "2026-10-30", total: 2_990_000 },
      ]),
    ).toBe("Peak Fri 2.99 M · low Mon 2.00 M");
    expect(presetRange("7d", new Date("2026-10-31T12:00:00Z"))).toEqual({
      from: "2026-10-25",
      to: "2026-10-31",
    });
    expect(presetRange("24h", new Date("2026-10-31T12:00:00Z"))).toEqual({
      from: "2026-10-31",
      to: "2026-10-31",
    });
  });
});
