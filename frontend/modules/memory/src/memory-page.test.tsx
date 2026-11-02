import { API, contextHandlers, p01Handlers, p02Handlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { MemoryPage as Page } from "./memory-page";

/** Tooltips need the provider the shell mounts. */
function MemoryPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

// Context handlers first: they override the gateway defaults (/config).
const handlers = () => [...contextHandlers(), ...p01Handlers(), ...p02Handlers()];
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

describe("MemoryPage", () => {
  it("lists users and memories with topic pills and likely duplicates", async () => {
    renderPage(MemoryPage, { path: "/i/$instance/memory", url: "/i/prod-agentos/memory" });
    expect(await screen.findByRole("heading", { name: "cus_48213" })).toBeInTheDocument();
    expect(
      await screen.findByText(/14 memories · written by support-triage, billing-agent and kb-researcher/),
    ).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Memories" });
    expect(within(list).getAllByRole("button")).toHaveLength(8);
    await waitFor(() => {
      expect(within(list).getAllByText("likely duplicate")).toHaveLength(2);
    });
    const topics = screen.getByRole("group", { name: "Filter by topic" });
    expect(within(topics).getByRole("button", { name: /billing\s*4/ })).toBeInTheDocument();
  });

  it("shows the source input of a memory and previews then applies an optimization", async () => {
    const user = userEvent.setup();
    const applied: boolean[] = [];
    server.use(
      http.post(`${API}/instances/:instance/memories/optimize`, async ({ request }) => {
        const body = (await request.json()) as { apply: boolean };
        applied.push(body.apply);
        return HttpResponse.json({
          user_id: "cus_48213",
          applied: body.apply,
          memories: [{ memory_id: "", memory: "Merged.", topics: [] }],
          memories_before: 8,
          memories_after: 1,
          tokens_before: 100,
          tokens_after: 40,
          tokens_saved: 60,
          reduction_percentage: 60,
        });
      }),
    );
    renderPage(MemoryPage, { path: "/i/$instance/memory", url: "/i/prod-agentos/memory?memory=mem_48213_3" });
    const editor = await screen.findByRole("complementary", { name: "Edit memory" });
    expect(await within(editor).findByText(/My card was charged twice for order #4471/)).toBeInTheDocument();
    expect(within(editor).getByRole("link", { name: "sess_9c41e2" })).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: /Optimize memories/ }));
    const preview = await screen.findByRole("region", { name: "Optimization preview" });
    expect(within(preview).getByText("Preview: 8 → 1 memories")).toBeInTheDocument();
    expect(applied).toEqual([false]);
    await user.click(within(preview).getByRole("button", { name: "Apply" }));
    await waitFor(() => {
      expect(applied).toEqual([false, true]);
    });
  });

  it("asks before deleting a memory", async () => {
    const user = userEvent.setup();
    let deleted: string | undefined;
    server.use(
      http.delete(`${API}/instances/:instance/os/memories/:id`, ({ params }) => {
        deleted = String(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPage(MemoryPage, { path: "/i/$instance/memory", url: "/i/prod-agentos/memory?memory=mem_48213_4" });
    const editor = await screen.findByRole("complementary", { name: "Edit memory" });
    await user.click(await within(editor).findByRole("button", { name: "Delete" }));
    expect(deleted).toBeUndefined();
    await user.click(await screen.findByRole("button", { name: "Delete memory" }));
    await waitFor(() => {
      expect(deleted).toBe("mem_48213_4");
    });
  });
});
