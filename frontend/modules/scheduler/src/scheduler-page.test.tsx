import {
  API,
  sampleOrgHandlers,
  renderPage,
  sampleSchedulerStatus,
  schedulerHandlers,
} from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { SchedulerPage as Page } from "./scheduler-page";

/** Tooltips need the provider the shell mounts. */
function SchedulerPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...sampleOrgHandlers(), ...schedulerHandlers()];
const server = setupServer(...handlers());
const open = (url = "/i/prod-agentos/scheduler") =>
  renderPage(SchedulerPage, { path: "/i/$instance/scheduler", url });

/** Opens "New schedule" once the scheduler status says the person may write. */
async function startNew(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "New schedule" })).toBeEnabled();
  });
  await user.click(screen.getByRole("button", { name: "New schedule" }));
}

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

describe("SchedulerPage", () => {
  it("shows the failure banner, the schedules and the scheduler status", async () => {
    open();
    const banner = (await screen.findByText(/daily-brief failed twice/)).closest('[role="alert"]');
    if (!(banner instanceof HTMLElement)) throw new Error("The failure banner is not an alert");
    expect(banner).toHaveTextContent("Timed out in web_search after 30 s. The schedule is still enabled.");
    expect(within(banner).getByRole("link", { name: "Open trace" })).toHaveAttribute(
      "href",
      "/i/prod-agentos/traces?run_id=run_db5",
    );

    const table = screen.getByRole("table", { name: "Schedules" });
    expect(within(table).getByText("Every 30 minutes, 08:00–18:59, Monday to Friday")).toBeInTheDocument();
    expect(within(table).getByText("*/30 8-18 * * 1-5 · America/New_York")).toBeInTheDocument();
    expect(within(table).getByText("workflow · daily-brief")).toBeInTheDocument();
    expect(within(table).getByText("ERROR ×2")).toBeInTheDocument();
    expect(within(table).getByText("NO RUNS")).toBeInTheDocument();
    expect(within(table).getByText("Disabled")).toBeInTheDocument();
    expect(within(table).getByRole("switch", { name: "Enable churn-digest" })).not.toBeChecked();
    expect(within(table).getByRole("switch", { name: "Enable kb-sync" })).toBeChecked();
    expect(
      screen.getByText("GET /schedules · 5 schedules · enable and disable need schedules:write"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Scheduler running · polls every 15 s")).toBeInTheDocument();

    // The first schedule is open: its failures and run history.
    const aside = screen.getByRole("complementary", { name: "Schedule details" });
    expect(within(aside).getByRole("heading", { name: "daily-brief" })).toBeInTheDocument();
    expect(
      within(aside).getByText(/The last 2 attempts failed: Timed out in web_search/),
    ).toBeInTheDocument();
    const runs = await within(aside).findByRole("list", { name: "Runs" });
    expect(within(runs).getByText("retry 1 of 1")).toBeInTheDocument();
    expect(within(runs).getByText("31.2 s")).toBeInTheDocument();
  });

  it("shows when a schedule runs, in local time and UTC, with the daylight-saving note", async () => {
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "stale-ticket-sweep" }));
    const aside = await screen.findByRole("complementary", { name: "Schedule details" });
    await within(aside).findByRole("heading", { name: "stale-ticket-sweep" });
    const when = within(aside).getByRole("region", { name: "When it runs" });
    expect(within(when).getByText("America/New_York")).toBeInTheDocument();
    const next = await within(when).findByRole("group", { name: "Next runs" });
    await within(next).findByText("Every 30 minutes, 08:00–18:59, Monday to Friday");
    const first = within(next).getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("Mon 2 Nov 2026 · 08:00");
    expect(first).toHaveTextContent("13:00 UTC");
    expect(first).toHaveAttribute("aria-current", "true");
    expect(
      within(when).getByText(
        "Daylight saving ends Sun 1 Nov in America/New_York: these runs move from 12:00 to 13:00 UTC.",
      ),
    ).toBeInTheDocument();
    expect(within(aside).getByText("/workflows/ticket-router/runs")).toBeInTheDocument();
  });

  it("asks for a reason before disabling, and sends it", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.post(`${API}/instances/:instance/schedules/:id/disable`, async ({ request }) => {
        sent = await request.clone().json();
        // Falls through to the stateful sample handler.
      }),
    );
    open();
    const toggle = await screen.findByRole("switch", { name: "Enable kb-sync" });
    await user.click(toggle);
    const dialog = await screen.findByRole("dialog", { name: "Disable kb-sync?" });
    await user.type(
      within(dialog).getByRole("textbox", { name: "Reason" }),
      "Help center migration this week",
    );
    await user.click(within(dialog).getByRole("button", { name: "Disable" }));
    await waitFor(() => {
      expect(sent).toEqual({ reason: "Help center migration this week" });
    });
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Enable kb-sync" })).not.toBeChecked();
    });
  });

  it("creates a schedule from the target picker", async () => {
    const user = userEvent.setup();
    let sent: Record<string, unknown> | undefined;
    server.use(
      http.post(`${API}/instances/:instance/schedules`, async ({ request }) => {
        sent = (await request.clone().json()) as Record<string, unknown>;
        // Falls through to the stateful sample handler.
      }),
    );
    open();
    await startNew(user);
    const dialog = await screen.findByRole("dialog", { name: "New schedule" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "churn digest!");
    expect(within(dialog).getByText(/Start with a letter or digit/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create schedule" })).toBeDisabled();
    await user.clear(within(dialog).getByRole("textbox", { name: "Name" }));
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "nightly-churn");
    await user.click(within(dialog).getByRole("radio", { name: "Team" }));
    await waitFor(() => {
      expect(within(dialog).getByLabelText("Endpoint")).toHaveTextContent("/teams/research-team/runs");
    });
    expect(within(dialog).getByRole("group", { name: "Next runs" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Create schedule" }));
    await waitFor(() => {
      expect(sent).toMatchObject({
        name: "nightly-churn",
        method: "POST",
        endpoint: "/teams/research-team/runs",
        cron_expr: "0 9 * * 1-5",
        payload: { message: "", stream: false },
        timeout_seconds: 3600,
        max_retries: 0,
        retry_delay_seconds: 60,
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "New schedule" })).not.toBeInTheDocument();
    });
  });

  it("marks cron fields the server rejects", async () => {
    const user = userEvent.setup();
    open();
    await startNew(user);
    const dialog = await screen.findByRole("dialog", { name: "New schedule" });
    const minute = within(dialog).getByRole("textbox", { name: "Minute" });
    await user.tripleClick(minute);
    await user.keyboard("75");
    await waitFor(() => {
      expect(within(dialog).getByRole("textbox", { name: "Minute" })).toHaveAttribute("aria-invalid", "true");
    });
    expect(within(dialog).getByText("This cron expression doesn't parse")).toBeInTheDocument();
  });

  it("offers custom endpoints to Instance admins only, and warns about undocumented paths", async () => {
    const user = userEvent.setup();
    const view = open();
    await startNew(user);
    let dialog = await screen.findByRole("dialog", { name: "New schedule" });
    await user.click(within(dialog).getByRole("radio", { name: "Custom endpoint" }));
    await user.type(within(dialog).getByRole("textbox", { name: "Path" }), "/internal/reindex");
    expect(
      await within(dialog).findByText("This path isn't in the instance's OpenAPI document."),
    ).toBeInTheDocument();
    view.unmount();

    server.use(
      http.get(`${API}/instances/:instance/schedules/status`, () =>
        HttpResponse.json({ ...sampleSchedulerStatus, can_custom_endpoint: false }),
      ),
    );
    open();
    await startNew(user);
    dialog = await screen.findByRole("dialog", { name: "New schedule" });
    expect(within(dialog).getByRole("radio", { name: "Team" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("radio", { name: "Custom endpoint" })).not.toBeInTheDocument();
  });

  it("disables writes for people without schedules:write", async () => {
    server.use(
      http.get(`${API}/instances/:instance/schedules/status`, () =>
        HttpResponse.json({ ...sampleSchedulerStatus, running: null, can_write: false, can_delete: false }),
      ),
    );
    open();
    expect(await screen.findByText("Scheduler status unknown")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New schedule" })).toBeDisabled();
    expect(await screen.findByRole("switch", { name: "Enable kb-sync" })).toBeDisabled();
    const aside = screen.getByRole("complementary", { name: "Schedule details" });
    expect(within(aside).getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(within(aside).getByRole("button", { name: "Delete" }).parentElement).toHaveAttribute(
      "title",
      "Needs schedules:delete",
    );
  });
});
