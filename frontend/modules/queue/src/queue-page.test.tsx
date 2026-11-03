import { API, p01Handlers, queueCountsOnlyHandlers, queueHandlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { QueuePage as Page } from "./queue-page";

/** Tooltips need the provider the shell mounts. */
function QueuePage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...p01Handlers(), ...queueHandlers()];
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

const PATH = "/i/$instance/queue";
const FAILED_JOB = "/i/prod-agentos/queue?status=failed&job=run_5c81e0";

describe("QueuePage", () => {
  it("shows health, workers and the config", async () => {
    renderPage(QueuePage, { path: PATH, url: "/i/prod-agentos/queue" });
    const waiting = await screen.findByRole("region", { name: "Waiting to start" });
    await waitFor(() => {
      expect(waiting).toHaveTextContent("/ 1,000");
    });
    expect(within(waiting).getByText("max_queue_depth · 429 when full")).toBeInTheDocument();
    const running = screen.getByRole("region", { name: "Running" });
    expect(running).toHaveTextContent("7/ 12 slots");
    expect(within(running).getByText("max_concurrency 4 × 3 replicas")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Waiting on 3 approvals →" })).toHaveAttribute(
      "href",
      "/i/prod-agentos/approvals",
    );
    expect(screen.getByRole("region", { name: "Failed jobs" })).toHaveTextContent(
      "kept 24 h · retention_seconds 86400",
    );
    expect(screen.getByText("Durable · PostgresDb · agno_jobs")).toBeInTheDocument();

    const workers = screen.getByRole("list", { name: "Workers" });
    const busiest = within(workers).getByRole("listitem", { name: "prod-agentos-1" });
    expect(within(busiest).getByRole("img", { name: "4 of 4 slots busy" })).toBeInTheDocument();
    expect(busiest).toHaveTextContent("4 of 4 running · deployment 2026-10-31.2");
    expect(busiest).toHaveTextContent(/heartbeat \d+ s ago/);
    expect(screen.getByText(/abandoned after 60 s without a heartbeat/)).toBeInTheDocument();

    expect(screen.getByRole("group", { name: "Queue config" })).toHaveTextContent("poll_interval 1.0");
    expect(screen.getByRole("tab", { name: /Completed/ })).toHaveTextContent("1,186");
  });

  it("lists failed jobs on the Failed tab and opens one with attempts and checkpoints", async () => {
    const user = userEvent.setup();
    renderPage(QueuePage, { path: PATH, url: "/i/prod-agentos/queue" });
    await user.click(await screen.findByRole("tab", { name: /Failed/ }));
    const table = await screen.findByRole("table", { name: "Jobs" });
    await waitFor(() => {
      expect(within(table).getAllByRole("row")).toHaveLength(4);
    });
    expect(within(table).queryByText("run_7d22c1")).not.toBeInTheDocument();
    expect(screen.getByText("Requeue grants one more attempt with the same run_id")).toBeInTheDocument();

    await user.click(within(table).getByRole("link", { name: "run_5c81e0" }));
    const aside = await screen.findByRole("complementary", { name: "Failed job run_5c81e0" });
    expect(await within(aside).findByText("Job failed")).toBeInTheDocument();
    expect(within(aside).getByText("Run ERROR")).toBeInTheDocument();
    const attempts = within(aside).getByRole("list", { name: "Attempts" });
    expect(within(attempts).getByText("Attempt 2 ended in ERROR · job marked failed")).toBeInTheDocument();
    expect(within(aside).getByText(/ModelProviderError/)).toBeInTheDocument();
    expect(within(aside).getByRole("radio", { name: /#2 After zendesk_search/ })).toBeChecked();
    expect(within(aside).getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("resumes from the selected checkpoint", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.post(`${API}/instances/:instance/queue/jobs/:job/resume`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ code: "x", status: 502, title: "stop here", type: "x" }, { status: 502 });
      }),
    );
    renderPage(QueuePage, { path: PATH, url: FAILED_JOB });
    const aside = await screen.findByRole("complementary", { name: "Failed job run_5c81e0" });
    await user.click(await within(aside).findByRole("button", { name: "Resume from #2" }));
    await waitFor(() => {
      expect(sent).toEqual({ message_index: 5 });
    });

    await user.click(within(aside).getByRole("radio", { name: /#1 After kb_lookup/ }));
    await user.click(within(aside).getByRole("button", { name: "Resume from #1" }));
    await waitFor(() => {
      expect(sent).toEqual({ message_index: 3 });
    });
  });

  it("offers a forced requeue when the job failed moments ago", async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/instances/:instance/queue/jobs/:job/requeue`, async ({ request }) => {
        const body = (await request.json()) as { force?: boolean };
        sent.push(body);
        if (!body.force)
          return HttpResponse.json(
            {
              type: "x",
              title: "Conflict",
              status: 409,
              code: "conflict",
              detail: "prod-agentos: run_5c81e0 failed 12 s ago.",
            },
            { status: 409 },
          );
        return HttpResponse.json({ code: "x", status: 502, title: "stop here", type: "x" }, { status: 502 });
      }),
    );
    renderPage(QueuePage, { path: PATH, url: FAILED_JOB });
    const aside = await screen.findByRole("complementary", { name: "Failed job run_5c81e0" });
    await user.click(await within(aside).findByRole("button", { name: "Requeue" }));
    const warning = await within(aside).findByRole("alert");
    expect(warning).toHaveTextContent("prod-agentos: run_5c81e0 failed 12 s ago.");
    await user.click(within(warning).getByRole("button", { name: "Requeue anyway" }));
    await waitFor(() => {
      expect(sent).toEqual([{}, { force: true }]);
    });
  });

  it("requeues a failed job", async () => {
    const user = userEvent.setup();
    renderPage(QueuePage, { path: PATH, url: FAILED_JOB });
    const aside = await screen.findByRole("complementary", { name: "Failed job run_5c81e0" });
    await user.click(await within(aside).findByRole("button", { name: "Requeue" }));
    const updated = await screen.findByRole("complementary", { name: "Job run_5c81e0" });
    expect(await within(updated).findByText("Job queued")).toBeInTheDocument();
  });

  it("shows counts and the reason to people who can't operate the queue", async () => {
    server.use(...queueCountsOnlyHandlers());
    renderPage(QueuePage, { path: PATH, url: FAILED_JOB });
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("You see counts only");
    expect(note).toHaveTextContent("Operators (queue:operate) reach it through the control plane");
    expect(screen.getByRole("region", { name: "Failed jobs" })).toHaveTextContent("3");
    expect(screen.getByText(/completed 1,186/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Jobs" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Workers" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });
});
